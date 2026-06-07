"""
Revenue Impact Attribution  (Phase 3)
=====================================
Maps intervention targeting + outcomes to membership-tier revenue:

  - MRR At Risk (targeted)  : expected monthly revenue under intervention
                              = sum(churn_probability x monthly_price). 100% data-driven.
  - Monthly Saved Revenue   : MRR At Risk discounted by an assumed program effectiveness
                              (segmented: retention vs. win-back reactivation).
  - Monthly Lost Revenue    : MRR of treated members who churned within 30 days (observed).
  - Net Financial Impact    : Saved MRR - intervention spend.
  - LTV Impact              : Saved MRR x average member lifetime (months).
  - Intervention ROI        : per-channel benefit vs. send cost.
  - Cohort Retention Decay  : Kaplan-Meier monthly survival curve.
  - Studio Leaderboard      : per-studio net impact ranking.

ATTRIBUTION CAVEAT
------------------
This is an *attribution model*, not a measured causal effect. The ONLY assumptions are the
two effectiveness factors below; every dollar is otherwise data-driven (model risk x real
tier price). Because interventions are dispatched as of the latest data date, there is no
forward window to observe re-engagement in this demo, so `confirmed_reengaged` will read 0
until real forward outcome data accrues. A true causal figure needs the treatment-vs-holdout
differential measured forward over time (see the dashboard A/B view).

Outputs:
  data/revenue_studio_leaderboard.parquet
  data/revenue_cohort_retention.parquet
"""

import os
import sys
import datetime
import pandas as pd
import numpy as np

DATA_DIR = "./data"
OUTCOMES_PATH = os.path.join(DATA_DIR, "intervention_outcomes.parquet")
LIFECYCLE_PATH = os.path.join(DATA_DIR, "member_lifecycle.parquet")
MEMBERS_PATH = os.path.join(DATA_DIR, "members.parquet")
GROUND_TRUTH_PATH = os.path.join(DATA_DIR, "ground_truth.parquet")
FEATURES_PATH = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")

LEADERBOARD_PATH = os.path.join(DATA_DIR, "revenue_studio_leaderboard.parquet")
RETENTION_PATH = os.path.join(DATA_DIR, "revenue_cohort_retention.parquet")

# Per-send cost by channel (USD). WinBackEmail is an email; Call is staff time.
CHANNEL_COSTS = {
    "Email": 0.01,
    "WinBackEmail": 0.01,
    "SMS": 0.05,
    "Push": 0.005,
    "Call": 5.00,
}
DEFAULT_CHANNEL_COST = 0.01

# Confirmed positive signals (need a forward data window to fire; tracked separately).
SAVED_OUTCOMES = {"re_engaged", "payment_resolved"}

# Attribution assumptions (the ONLY non-data-driven inputs). Tune as real outcomes accrue.
RETENTION_EFFECTIVENESS = 0.25     # share of at-risk churn the program is assumed to prevent
WINBACK_REACTIVATION_RATE = 0.08   # share of cancelled members assumed to reactivate
REACTIVATION_STAGES = {"win_back_eligible", "win_back_expired", "cancelled"}

FALLBACK_AVG_LIFETIME_MONTHS = 18.0


# ==============================================================================
# HELPERS
# ==============================================================================
def _channel_cost(action_type: str) -> float:
    return CHANNEL_COSTS.get(action_type, DEFAULT_CHANNEL_COST)


def _effectiveness(stage: str) -> float:
    return WINBACK_REACTIVATION_RATE if stage in REACTIVATION_STAGES else RETENTION_EFFECTIVENESS


def average_member_lifetime_months() -> float:
    """Mean observed lifetime (join -> churn) of churned members, in months."""
    if not (os.path.exists(MEMBERS_PATH) and os.path.exists(GROUND_TRUTH_PATH)):
        return FALLBACK_AVG_LIFETIME_MONTHS
    members = pd.read_parquet(MEMBERS_PATH)[["member_id", "join_date"]]
    gt = pd.read_parquet(GROUND_TRUTH_PATH)[["member_id", "churned", "churn_date"]]
    df = members.merge(gt, on="member_id")
    churned = df[df["churned"] == True].copy()
    if churned.empty:
        return FALLBACK_AVG_LIFETIME_MONTHS
    days = (pd.to_datetime(churned["churn_date"]) - pd.to_datetime(churned["join_date"])).dt.days
    days = days[days > 0]
    return round(float(days.mean()) / 30.44, 1) if not days.empty else FALLBACK_AVG_LIFETIME_MONTHS


def _load_treated_members() -> pd.DataFrame:
    """One row per treated member with risk, price, segment and expected-value economics.

    Revenue is attributed at the MEMBER level (a member's MRR is counted once even with
    several touches); send COST is counted per touch separately.
    """
    outcomes = pd.read_parquet(OUTCOMES_PATH)
    lifecycle = pd.read_parquet(LIFECYCLE_PATH)[
        ["hashed_member_id", "monthly_price", "home_studio_id", "churn_probability", "stage"]
    ].drop_duplicates("hashed_member_id")

    o = outcomes.copy()
    o["is_lost"] = o["churned_within_30d"].fillna(False).astype(bool)
    o["is_confirmed_save"] = o["outcome_30d"].isin(SAVED_OUTCOMES)

    per = o.groupby("hashed_member_id").agg(
        touches=("audit_id", "count"),
        is_lost=("is_lost", "any"),
        confirmed_save=("is_confirmed_save", "any"),
        primary_channel=("action_type", lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0]),
    ).reset_index()

    per = per.merge(lifecycle, on="hashed_member_id", how="left")
    per["monthly_price"] = per["monthly_price"].fillna(0.0)
    per["churn_probability"] = per["churn_probability"].fillna(0.0)
    per["stage"] = per["stage"].fillna("unknown")
    per["segment"] = np.where(per["stage"].isin(REACTIVATION_STAGES), "reactivation", "retention")
    per["effectiveness"] = per["stage"].apply(_effectiveness)
    per["targeted_mrr"] = per["churn_probability"] * per["monthly_price"]
    per["saved_mrr"] = per["targeted_mrr"] * per["effectiveness"]
    per["saved_members_exp"] = per["churn_probability"] * per["effectiveness"]
    per["lost_mrr"] = per["monthly_price"].where(per["is_lost"], 0.0)
    return per


# ==============================================================================
# CORE METRICS
# ==============================================================================
def compute_revenue_summary() -> dict:
    members = _load_treated_members()
    outcomes = pd.read_parquet(OUTCOMES_PATH)

    spend = float(outcomes["action_type"].map(_channel_cost).sum())
    mrr_at_risk = float(members["targeted_mrr"].sum())
    saved_mrr = float(members["saved_mrr"].sum())
    lost_mrr = float(members["lost_mrr"].sum())
    net_impact = saved_mrr - spend
    avg_lifetime = average_member_lifetime_months()

    return {
        "members_treated": int(members["hashed_member_id"].nunique()),
        "est_members_saved": round(float(members["saved_members_exp"].sum()), 1),
        "confirmed_reengaged": int(members["confirmed_save"].sum()),
        "members_lost": int(members["is_lost"].sum()),
        "mrr_at_risk": round(mrr_at_risk, 2),
        "saved_mrr": round(saved_mrr, 2),
        "lost_mrr": round(lost_mrr, 2),
        "intervention_spend": round(spend, 2),
        "net_monthly_impact": round(net_impact, 2),
        "avg_lifetime_months": avg_lifetime,
        "ltv_impact": round(saved_mrr * avg_lifetime, 2),
        "retention_effectiveness": RETENTION_EFFECTIVENESS,
        "winback_rate": WINBACK_REACTIVATION_RATE,
        "roi_ratio": round(net_impact / spend, 1) if spend > 0 else None,
    }


def get_channel_roi() -> pd.DataFrame:
    """Per-channel sends, cost, expected saved MRR and ROI (saved attributed to the
    member's primary channel)."""
    members = _load_treated_members()
    outcomes = pd.read_parquet(OUTCOMES_PATH).copy()
    outcomes["cost"] = outcomes["action_type"].map(_channel_cost)

    cost = outcomes.groupby("action_type")["cost"].agg(sends="count", cost="sum")
    saved = members.groupby("primary_channel").agg(
        members_saved=("saved_members_exp", "sum"),
        saved_mrr=("saved_mrr", "sum"),
    )
    roi = cost.join(saved, how="left").fillna(0)
    roi["cost"] = roi["cost"].round(2)
    roi["members_saved"] = roi["members_saved"].round(1)
    roi["saved_mrr"] = roi["saved_mrr"].round(2)
    roi["net_monthly"] = (roi["saved_mrr"] - roi["cost"]).round(2)
    roi["roi_ratio"] = roi.apply(
        lambda r: round((r["saved_mrr"] - r["cost"]) / r["cost"], 1) if r["cost"] > 0 else None, axis=1
    )
    return roi.reset_index().rename(columns={"action_type": "channel"})


def get_studio_leaderboard() -> pd.DataFrame:
    """Per-studio retention economics, ranked by net monthly impact."""
    members = _load_treated_members()
    outcomes = pd.read_parquet(OUTCOMES_PATH).copy()
    lifecycle = pd.read_parquet(LIFECYCLE_PATH)[
        ["hashed_member_id", "home_studio_id"]
    ].drop_duplicates("hashed_member_id")

    outcomes["cost"] = outcomes["action_type"].map(_channel_cost)
    spend = outcomes.merge(lifecycle, on="hashed_member_id", how="left").groupby("home_studio_id")["cost"].sum()

    board = members.groupby("home_studio_id").agg(
        members_treated=("hashed_member_id", "nunique"),
        est_saved=("saved_members_exp", "sum"),
        members_lost=("is_lost", "sum"),
        mrr_at_risk=("targeted_mrr", "sum"),
        saved_mrr=("saved_mrr", "sum"),
        lost_mrr=("lost_mrr", "sum"),
    ).reset_index()

    for c in ["est_saved", "mrr_at_risk", "saved_mrr", "lost_mrr"]:
        board[c] = board[c].round(2)
    board["spend"] = board["home_studio_id"].map(spend).fillna(0).round(2)
    board["net_monthly"] = (board["saved_mrr"] - board["spend"]).round(2)
    board = board.sort_values("net_monthly", ascending=False).reset_index(drop=True)
    board.insert(0, "rank", board.index + 1)
    return board


def get_cohort_retention(max_months: int = 36) -> pd.DataFrame:
    """Kaplan-Meier monthly retention curve across the member base (handles right-censoring
    of members who haven't churned yet)."""
    members = pd.read_parquet(MEMBERS_PATH)[["member_id", "join_date"]]
    gt = pd.read_parquet(GROUND_TRUTH_PATH)[["member_id", "churned", "churn_date"]]
    df = members.merge(gt, on="member_id")
    df["join_date"] = pd.to_datetime(df["join_date"])
    df["churn_date"] = pd.to_datetime(df["churn_date"])

    as_of = pd.to_datetime(pd.read_parquet(FEATURES_PATH, columns=["date_day"])["date_day"]).max()
    event = df["churned"].fillna(False).astype(bool).to_numpy()
    end = df["churn_date"].where(df["churned"] == True, as_of)
    dur_months = ((end - df["join_date"]).dt.days / 30.44).clip(lower=0).to_numpy()

    rows = []
    surv = 1.0
    for m in range(1, max_months + 1):
        at_risk = int((dur_months >= (m - 1)).sum())
        events = int((event & (dur_months >= (m - 1)) & (dur_months < m)).sum())
        if at_risk > 0:
            surv *= (1 - events / at_risk)
        rows.append({"month": m, "retention": round(surv, 4), "at_risk": at_risk})
    return pd.DataFrame(rows)


# ==============================================================================
# FRANCHISE PDF REPORT  (matplotlib PdfPages -- no extra dependency)
# ==============================================================================
def generate_franchise_pdf(output_path: str = "franchise_revenue_report.pdf", studio: str | None = None) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    summary = compute_revenue_summary()
    board = get_studio_leaderboard()
    retention = get_cohort_retention()
    today = datetime.date.today().strftime("%B %d, %Y")
    scope = f"Studio {studio}" if studio else "All Studios"

    with PdfPages(output_path) as pdf:
        fig = plt.figure(figsize=(8.5, 11))
        fig.patch.set_facecolor("white")
        fig.text(0.5, 0.95, "HOTWORX — Retention Revenue Impact", ha="center", fontsize=18, fontweight="bold")
        fig.text(0.5, 0.925, f"{scope}   |   Generated {today}", ha="center", fontsize=10, color="#555")
        fig.text(0.06, 0.90,
                 f"Attribution estimate (retention {int(RETENTION_EFFECTIVENESS*100)}%, win-back {int(WINBACK_REACTIVATION_RATE*100)}%) — not a measured causal result.",
                 fontsize=8, style="italic", color="#999")

        lines = [
            ("Members treated", f"{summary['members_treated']:,}"),
            ("Est. members saved", f"{summary['est_members_saved']:,.0f}"),
            ("MRR At Risk (targeted)", f"${summary['mrr_at_risk']:,.2f}"),
            ("Monthly Saved Revenue", f"${summary['saved_mrr']:,.2f}"),
            ("Monthly Lost Revenue", f"${summary['lost_mrr']:,.2f}"),
            ("Intervention Spend", f"${summary['intervention_spend']:,.2f}"),
            ("Net Monthly Impact", f"${summary['net_monthly_impact']:,.2f}"),
            (f"Est. LTV Impact ({summary['avg_lifetime_months']} mo)", f"${summary['ltv_impact']:,.2f}"),
            ("Program ROI", f"{summary['roi_ratio']}x" if summary["roi_ratio"] is not None else "n/a"),
        ]
        y = 0.86
        for label, val in lines:
            fig.text(0.08, y, label, fontsize=11, color="#333")
            fig.text(0.92, y, val, fontsize=11, fontweight="bold", ha="right")
            y -= 0.034

        ax1 = fig.add_axes([0.1, 0.36, 0.36, 0.18])
        ax1.bar(["Saved", "Lost"], [summary["saved_mrr"], summary["lost_mrr"]], color=["#10B981", "#EF4444"])
        ax1.set_title("Monthly MRR", fontsize=10)
        ax1.set_ylabel("USD")

        ax2 = fig.add_axes([0.56, 0.36, 0.36, 0.18])
        ax2.plot(retention["month"], retention["retention"] * 100, color="#5F57FF", linewidth=2)
        ax2.set_title("Cohort Retention (Kaplan-Meier)", fontsize=10)
        ax2.set_xlabel("Months since join")
        ax2.set_ylabel("% retained")
        ax2.set_ylim(0, 100)

        ax3 = fig.add_axes([0.08, 0.05, 0.84, 0.24])
        ax3.axis("off")
        top = board.head(10)[["rank", "home_studio_id", "est_saved", "saved_mrr", "net_monthly"]]
        table = ax3.table(
            cellText=top.round(2).values,
            colLabels=["#", "Studio", "Est. Saved", "Saved MRR", "Net/mo"],
            cellLoc="center", loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1, 1.4)
        ax3.set_title("Studio Leaderboard (Top 10 by Net Monthly Impact)", fontsize=10, pad=12)

        pdf.savefig(fig)
        plt.close(fig)
    return output_path


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    print("=" * 60)
    print("REVENUE IMPACT ATTRIBUTION  (Phase 3)")
    print("=" * 60)
    for label, path in [("Outcomes", OUTCOMES_PATH), ("Lifecycle", LIFECYCLE_PATH)]:
        if not os.path.exists(path):
            print(f"Error: {label} not found at {path}. Run Phase 1 first.")
            sys.exit(1)

    s = compute_revenue_summary()
    print("\nPROGRAM ECONOMICS (monthly)")
    print("-" * 60)
    print(f"  Members treated / est. saved / lost : {s['members_treated']:,} / {s['est_members_saved']:,.0f} / {s['members_lost']:,}")
    print(f"  MRR At Risk (targeted, data-driven) : ${s['mrr_at_risk']:,.2f}")
    print(f"  Monthly Saved Revenue (estimated)   : ${s['saved_mrr']:,.2f}")
    print(f"  Monthly Lost Revenue (observed)     : ${s['lost_mrr']:,.2f}")
    print(f"  Intervention Spend                  : ${s['intervention_spend']:,.2f}")
    print(f"  Net Monthly Impact                  : ${s['net_monthly_impact']:,.2f}")
    print(f"  Avg lifetime / LTV impact           : {s['avg_lifetime_months']} mo  ->  ${s['ltv_impact']:,.2f}")
    print(f"  Program ROI                         : {s['roi_ratio']}x")
    print(f"  (Assumptions: retention {int(RETENTION_EFFECTIVENESS*100)}%, win-back {int(WINBACK_REACTIVATION_RATE*100)}%; "
          f"confirmed re-engagements so far: {s['confirmed_reengaged']})")

    print("\nCHANNEL ROI")
    print("-" * 60)
    print(get_channel_roi().to_string(index=False))

    board = get_studio_leaderboard()
    print("\nSTUDIO LEADERBOARD (top 10 by net monthly impact)")
    print("-" * 60)
    print(board.head(10).to_string(index=False))

    retention = get_cohort_retention()
    board.to_parquet(LEADERBOARD_PATH, index=False)
    retention.to_parquet(RETENTION_PATH, index=False)
    print(f"\nSaved leaderboard -> {LEADERBOARD_PATH}")
    print(f"Saved retention   -> {RETENTION_PATH}  (retention@12mo = {retention.iloc[11]['retention']:.1%})")
    print("=" * 60)


if __name__ == "__main__":
    main()
