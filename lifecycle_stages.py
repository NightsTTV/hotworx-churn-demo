"""
Member Lifecycle Stage Classification Engine
=============================================
Classifies every member into one of 7 lifecycle stages based on their current
behavioral features, churn risk scores, and membership status.

Stages:
  onboarding        — Active, tenure ≤ 30 days
  engaged           — Active, ≥ 3 sessions in last 30d, Low risk tier
  at_risk           — Active, Medium/High/Critical risk tier
  lapsed            — Active (still paying) but 0 sessions in last 30d
  cancelled         — Membership ended
  win_back_eligible — Cancelled 7–90 days ago
  win_back_expired  — Cancelled > 90 days ago

Outputs: data/member_lifecycle.parquet
"""

import os
import sys
import datetime
import pandas as pd
import duckdb

DATA_DIR = "./data"

FEATURES_PATH = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
SCORES_PATH = os.path.join(DATA_DIR, "churn_scores_daily.parquet")
GROUND_TRUTH_PATH = os.path.join(DATA_DIR, "ground_truth.parquet")
MEMBERSHIPS_PATH = os.path.join(DATA_DIR, "memberships.parquet")
IDENTITY_PATH = os.path.join(DATA_DIR, "int_member_identity.parquet")
LIFECYCLE_PATH = os.path.join(DATA_DIR, "member_lifecycle.parquet")
PRIOR_LIFECYCLE_PATH = LIFECYCLE_PATH  # used to detect stage transitions


def classify_member_stage(
    tenure_days: int,
    sessions_attended_30d: int,
    risk_tier: str,
    is_cancelled: bool,
    days_since_cancellation: int | None,
    days_since_last_session: int,
) -> str:
    """Deterministic stage classifier. Order of precedence matters."""

    # 1. Cancelled members first — then split into win-back windows
    if is_cancelled:
        if days_since_cancellation is not None:
            if days_since_cancellation < 7:
                # Just cancelled — still counted as cancelled, not yet in win-back
                return "cancelled"
            elif days_since_cancellation <= 90:
                return "win_back_eligible"
            else:
                return "win_back_expired"
        return "cancelled"

    # 2. Active members — onboarding takes priority over risk-based stages
    if tenure_days <= 30:
        return "onboarding"

    # 3. Lapsed: paying but completely inactive (0 sessions in 30d)
    #    This is distinct from at_risk — they haven't even been booking
    if sessions_attended_30d == 0 and days_since_last_session > 30:
        return "lapsed"

    # 4. At-risk based on churn model output
    if risk_tier in ("Medium", "High", "Critical"):
        return "at_risk"

    # 5. Engaged: active and attending regularly with low risk
    if sessions_attended_30d >= 3 and risk_tier == "Low":
        return "engaged"

    # 6. Fallback — low-frequency but not flagged by model
    #    Members with 1-2 sessions and Low risk — still engaged, just light users
    return "engaged"


def compute_lifecycle_stages(as_of_date: datetime.date | None = None) -> pd.DataFrame:
    """Compute lifecycle stages for all known members as of a given date.

    Args:
        as_of_date: Snapshot date. Defaults to the latest score date in the data.

    Returns:
        DataFrame with columns: hashed_member_id, member_id, stage,
        stage_entered_at, previous_stage, days_in_stage, home_studio_id,
        monthly_price, tenure_days, risk_tier, churn_probability,
        sessions_attended_30d, days_since_last_session
    """
    # ---- Validate input files ----
    for label, path in [
        ("Features", FEATURES_PATH),
        ("Scores", SCORES_PATH),
        ("Ground truth", GROUND_TRUTH_PATH),
        ("Memberships", MEMBERSHIPS_PATH),
    ]:
        if not os.path.exists(path):
            print(f"Error: {label} not found at {path}. Run the pipeline first.")
            sys.exit(1)

    # ---- Load data ----
    con = duckdb.connect(database=":memory:")

    features_df = pd.read_parquet(FEATURES_PATH)
    scores_df = pd.read_parquet(SCORES_PATH)
    gt_df = pd.read_parquet(GROUND_TRUTH_PATH)
    memberships_df = pd.read_parquet(MEMBERSHIPS_PATH)

    # Resolve identity for member_id mapping
    import secure_data
    identity_df = secure_data.read_encrypted_parquet(IDENTITY_PATH)

    # Determine snapshot date
    latest_score_date = scores_df["score_date"].max()
    if as_of_date is None:
        as_of_date = latest_score_date
    print(f"Computing lifecycle stages as of: {as_of_date}")

    # ---- Build the active member snapshot ----
    # Latest features for scored members
    latest_features = features_df[features_df["date_day"] == as_of_date].copy()
    latest_scores = scores_df[scores_df["score_date"] == as_of_date].copy()

    # Merge features + scores
    active_df = latest_features.merge(
        latest_scores[["hashed_member_id", "churn_probability", "risk_tier"]],
        on="hashed_member_id",
        how="left",
    )

    # Add member_id from identity
    active_df = active_df.merge(
        identity_df[["hashed_member_id", "member_id"]],
        on="hashed_member_id",
        how="left",
    )

    # ---- Identify cancelled members not in the active snapshot ----
    # Ground truth knows who churned and when
    cancelled_df = gt_df[gt_df["churned"] == True].copy()
    cancelled_df["churn_date"] = pd.to_datetime(cancelled_df["churn_date"]).dt.date

    # Members in ground_truth but NOT in the active feature snapshot are cancelled
    active_member_ids = set(active_df["member_id"].dropna())
    all_member_ids = set(gt_df["member_id"])

    # ---- Classify active members ----
    lifecycle_records = []

    for _, row in active_df.iterrows():
        member_id = row.get("member_id")
        hashed_id = row["hashed_member_id"]
        tenure = int(row.get("tenure_days", 0))
        sessions_30d = int(row.get("sessions_attended_30d", 0))
        risk_tier = row.get("risk_tier", "Low")
        days_since = int(row.get("days_since_last_session", 0))
        prob = float(row.get("churn_probability", 0.0))

        stage = classify_member_stage(
            tenure_days=tenure,
            sessions_attended_30d=sessions_30d,
            risk_tier=risk_tier,
            is_cancelled=False,
            days_since_cancellation=None,
            days_since_last_session=days_since,
        )

        lifecycle_records.append({
            "hashed_member_id": hashed_id,
            "member_id": member_id,
            "stage": stage,
            "home_studio_id": row.get("home_studio_id"),
            "monthly_price": row.get("monthly_price"),
            "tenure_days": tenure,
            "risk_tier": risk_tier,
            "churn_probability": prob,
            "sessions_attended_30d": sessions_30d,
            "days_since_last_session": days_since,
            "snapshot_date": as_of_date,
        })

    # ---- Classify cancelled members (not in active snapshot) ----
    cancelled_member_ids = all_member_ids - active_member_ids

    for _, row in cancelled_df[cancelled_df["member_id"].isin(cancelled_member_ids)].iterrows():
        member_id = row["member_id"]
        churn_date = row["churn_date"]

        # Look up identity hash
        id_match = identity_df[identity_df["member_id"] == member_id]
        if id_match.empty:
            continue
        hashed_id = id_match.iloc[0]["hashed_member_id"]

        # Look up membership info
        mb_match = memberships_df[memberships_df["member_id"] == member_id]
        monthly_price = mb_match.iloc[0]["monthly_price"] if not mb_match.empty else 0.0
        studio_id = mb_match.iloc[0]["studio_id"] if not mb_match.empty else None

        # Calculate days since cancellation
        if isinstance(as_of_date, str):
            as_of_dt = datetime.date.fromisoformat(as_of_date)
        else:
            as_of_dt = as_of_date
        if isinstance(churn_date, str):
            churn_dt = datetime.date.fromisoformat(churn_date)
        else:
            churn_dt = churn_date

        days_since_cancel = (as_of_dt - churn_dt).days if churn_dt else 0

        stage = classify_member_stage(
            tenure_days=0,
            sessions_attended_30d=0,
            risk_tier="Low",
            is_cancelled=True,
            days_since_cancellation=days_since_cancel,
            days_since_last_session=999,
        )

        lifecycle_records.append({
            "hashed_member_id": hashed_id,
            "member_id": member_id,
            "stage": stage,
            "home_studio_id": studio_id,
            "monthly_price": monthly_price,
            "tenure_days": 0,
            "risk_tier": "N/A",
            "churn_probability": 1.0,
            "sessions_attended_30d": 0,
            "days_since_last_session": 999,
            "snapshot_date": as_of_date,
        })

    lifecycle_df = pd.DataFrame(lifecycle_records)

    # ---- Detect stage transitions from prior snapshot ----
    lifecycle_df["previous_stage"] = None
    lifecycle_df["stage_entered_at"] = as_of_date
    lifecycle_df["days_in_stage"] = 0

    if os.path.exists(PRIOR_LIFECYCLE_PATH):
        try:
            prior_df = pd.read_parquet(PRIOR_LIFECYCLE_PATH)
            if not prior_df.empty:
                prior_lookup = prior_df.set_index("hashed_member_id")[
                    ["stage", "stage_entered_at", "days_in_stage"]
                ].to_dict("index")

                for idx, row in lifecycle_df.iterrows():
                    hid = row["hashed_member_id"]
                    if hid in prior_lookup:
                        prior = prior_lookup[hid]
                        if prior["stage"] == row["stage"]:
                            # Same stage — carry forward entry date and increment days
                            lifecycle_df.at[idx, "stage_entered_at"] = prior["stage_entered_at"]
                            lifecycle_df.at[idx, "previous_stage"] = prior["stage"]
                            prior_days = prior.get("days_in_stage", 0) or 0
                            lifecycle_df.at[idx, "days_in_stage"] = prior_days + 1
                        else:
                            # Stage changed — record transition
                            lifecycle_df.at[idx, "previous_stage"] = prior["stage"]
                            lifecycle_df.at[idx, "stage_entered_at"] = as_of_date
                            lifecycle_df.at[idx, "days_in_stage"] = 0
        except Exception as e:
            print(f"Warning: Could not read prior lifecycle data: {e}")

    return lifecycle_df


def run_lifecycle_classification():
    """Main entry point: compute stages, print summary, save to parquet."""
    print("=" * 60)
    print("MEMBER LIFECYCLE STAGE CLASSIFICATION ENGINE")
    print("=" * 60)

    lifecycle_df = compute_lifecycle_stages()

    # ---- Summary Report ----
    print("\n" + "-" * 60)
    print("LIFECYCLE STAGE DISTRIBUTION")
    print("-" * 60)

    stage_order = [
        "onboarding", "engaged", "at_risk", "lapsed",
        "cancelled", "win_back_eligible", "win_back_expired",
    ]
    stage_counts = lifecycle_df["stage"].value_counts()

    total = len(lifecycle_df)
    for stage in stage_order:
        count = stage_counts.get(stage, 0)
        pct = (count / total) * 100 if total > 0 else 0
        bar = "█" * int(pct / 2)
        print(f"  {stage:22s}  {count:5,d}  ({pct:5.1f}%)  {bar}")

    print(f"\n  {'TOTAL':22s}  {total:5,d}")

    # Transition summary
    transitions = lifecycle_df[
        (lifecycle_df["previous_stage"].notna()) &
        (lifecycle_df["previous_stage"] != lifecycle_df["stage"])
    ]
    if not transitions.empty:
        print(f"\n  Stage transitions detected: {len(transitions)}")
        transition_pairs = transitions.groupby(["previous_stage", "stage"]).size()
        for (from_s, to_s), count in transition_pairs.items():
            print(f"    {from_s} → {to_s}: {count}")

    # Win-back revenue opportunity
    wb = lifecycle_df[lifecycle_df["stage"] == "win_back_eligible"]
    if not wb.empty:
        wb_revenue = wb["monthly_price"].sum()
        print(f"\n  💰 Win-Back Revenue Opportunity: ${wb_revenue:,.2f}/mo ({len(wb)} members)")

    # ---- Save ----
    lifecycle_df.to_parquet(LIFECYCLE_PATH, index=False)
    print(f"\nSaved {len(lifecycle_df):,} lifecycle records to: {LIFECYCLE_PATH}")

    print("=" * 60)
    print("LIFECYCLE CLASSIFICATION COMPLETED")
    print("=" * 60)

    return lifecycle_df


if __name__ == "__main__":
    run_lifecycle_classification()
