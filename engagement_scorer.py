"""
Engagement Scoring & Upsell Segmentation  (Phase 5)
===================================================
Computes a composite 0-100 engagement score per active member from the daily feature
table, then segments members to drive upsell / right-sizing / re-engagement campaigns.

Composite weighting (sums to 100%):
  - Session utilization  35%   (sessions_attended_30d vs. a 3x/week target)
  - App usage            25%   (app_logins_30d)
  - Email response       15%   (email_open_rate_30d)
  - Retail spend         15%   (retail_spend_30d)
  - Consistency          10%   (recency of last attended session)

Segments (a member's most actionable label; precedence top-down):
  - upsell_candidate     : Basic tier + high engagement   -> pitch VIP/Premium
  - under_engaged_payer  : Premium tier + low engagement   -> right-size / re-engage
  - at_risk_silent       : very low engagement             -> proactive nudge
  - champion             : high engagement (VIP/Premium)   -> referral/promoter
  - engaged              : healthy, no action

Output: data/member_engagement.parquet
"""

import os
import sys
import pandas as pd
import numpy as np

DATA_DIR = "./data"
FEATURES_PATH = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
SCORES_PATH = os.path.join(DATA_DIR, "churn_scores_daily.parquet")
ENGAGEMENT_PATH = os.path.join(DATA_DIR, "member_engagement.parquet")

# Component weights (must sum to 1.0).
WEIGHTS = {
    "session_utilization": 0.35,
    "app_usage": 0.25,
    "email_response": 0.15,
    "retail_spend": 0.15,
    "consistency": 0.10,
}

# "100%" targets used to normalize each raw feature to 0-100.
TARGET_SESSIONS_30D = 12.0   # ~3x/week
TARGET_LOGINS_30D = 20.0
TARGET_RETAIL_30D = 50.0     # USD
CONSISTENCY_WINDOW_DAYS = 30.0

# Segment thresholds.
HIGH_ENGAGEMENT = 70
CHAMPION_ENGAGEMENT = 75
LOW_ENGAGEMENT = 40
SILENT_ENGAGEMENT = 25


def _scaled(series: pd.Series, target: float) -> pd.Series:
    return (series.fillna(0).clip(lower=0) / target).clip(upper=1.0) * 100.0


def compute_engagement() -> pd.DataFrame:
    if not os.path.exists(FEATURES_PATH):
        print(f"Error: feature table not found at {FEATURES_PATH}. Run the pipeline first.")
        sys.exit(1)

    df = pd.read_parquet(FEATURES_PATH)
    df["date_day"] = pd.to_datetime(df["date_day"])
    latest = df["date_day"].max()
    snap = df[df["date_day"] == latest].copy()

    # --- Component scores (each 0-100) ---
    snap["session_utilization"] = _scaled(snap["sessions_attended_30d"], TARGET_SESSIONS_30D)
    snap["app_usage"] = _scaled(snap["app_logins_30d"], TARGET_LOGINS_30D)
    snap["email_response"] = (snap["email_open_rate_30d"].fillna(0).clip(0, 1)) * 100.0
    snap["retail_spend"] = _scaled(snap["retail_spend_30d"], TARGET_RETAIL_30D)
    snap["consistency"] = (
        (1 - (snap["days_since_last_session"].fillna(999) / CONSISTENCY_WINDOW_DAYS)).clip(lower=0, upper=1) * 100.0
    )

    # --- Composite ---
    snap["engagement_score"] = (
        WEIGHTS["session_utilization"] * snap["session_utilization"]
        + WEIGHTS["app_usage"] * snap["app_usage"]
        + WEIGHTS["email_response"] * snap["email_response"]
        + WEIGHTS["retail_spend"] * snap["retail_spend"]
        + WEIGHTS["consistency"] * snap["consistency"]
    ).round(1)

    # --- Join churn probability (for the dual gauge) ---
    if os.path.exists(SCORES_PATH):
        scores = pd.read_parquet(SCORES_PATH)[["hashed_member_id", "churn_probability", "risk_tier"]]
        snap = snap.merge(scores, on="hashed_member_id", how="left")
    else:
        snap["churn_probability"] = np.nan
        snap["risk_tier"] = "N/A"

    snap["segment"] = snap.apply(_segment, axis=1)

    cols = [
        "hashed_member_id", "home_studio_id", "membership_tier", "monthly_price",
        "engagement_score", "session_utilization", "app_usage", "email_response",
        "retail_spend", "consistency", "churn_probability", "risk_tier", "segment",
    ]
    out = snap[cols].copy()
    out[["session_utilization", "app_usage", "email_response", "retail_spend", "consistency"]] = (
        out[["session_utilization", "app_usage", "email_response", "retail_spend", "consistency"]].round(1)
    )
    return out


def _segment(row) -> str:
    score = row["engagement_score"]
    tier = row["membership_tier"]
    if tier == "Basic" and score >= HIGH_ENGAGEMENT:
        return "upsell_candidate"
    if tier == "Premium" and score < LOW_ENGAGEMENT:
        return "under_engaged_payer"
    if score < SILENT_ENGAGEMENT:
        return "at_risk_silent"
    if score >= CHAMPION_ENGAGEMENT:
        return "champion"
    return "engaged"


def get_segment_summary(eng: pd.DataFrame | None = None) -> pd.DataFrame:
    if eng is None:
        eng = pd.read_parquet(ENGAGEMENT_PATH)
    summ = eng.groupby("segment").agg(
        members=("hashed_member_id", "count"),
        avg_engagement=("engagement_score", "mean"),
        avg_churn_risk=("churn_probability", "mean"),
        monthly_revenue=("monthly_price", "sum"),
    ).round(2).reset_index()
    return summ.sort_values("members", ascending=False).reset_index(drop=True)


def main():
    print("=" * 60)
    print("ENGAGEMENT SCORING & UPSELL SEGMENTATION  (Phase 5)")
    print("=" * 60)
    eng = compute_engagement()
    eng.to_parquet(ENGAGEMENT_PATH, index=False)

    print(f"\nScored {len(eng):,} active members.")
    print(f"  Engagement score range : {eng['engagement_score'].min():.1f} - {eng['engagement_score'].max():.1f}")
    print(f"  Mean engagement        : {eng['engagement_score'].mean():.1f}")

    print("\nSEGMENTS")
    print("-" * 60)
    print(get_segment_summary(eng).to_string(index=False))

    # Tier-mismatch verification
    up = eng[eng["segment"] == "upsell_candidate"]
    uep = eng[eng["segment"] == "under_engaged_payer"]
    print("\nTIER-MISMATCH CHECKS")
    print("-" * 60)
    print(f"  upsell_candidate     : {len(up):,} members, all Basic? {bool((up['membership_tier'] == 'Basic').all())}")
    print(f"  under_engaged_payer  : {len(uep):,} members, all Premium? {bool((uep['membership_tier'] == 'Premium').all())}")
    upsell_rev = float(up["monthly_price"].sum())
    print(f"  Upsell pipeline (current Basic MRR of candidates): ${upsell_rev:,.2f}/mo")

    print(f"\nSaved -> {ENGAGEMENT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
