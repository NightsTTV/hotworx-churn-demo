"""
Intervention Outcome Tracker
=============================
For each intervention dispatched (from the audit log), looks forward 7/14/30 days
to measure whether the member re-engaged, resolved a payment issue, or churned.

Computes per-intervention-type and per-risk-tier conversion rates, enabling the
closed-loop feedback needed for adaptive intervention routing.

Outputs: data/intervention_outcomes.parquet
"""

import os
import sys
import datetime
import pandas as pd
import numpy as np

DATA_DIR = "./data"

AUDIT_LOG_PATH = os.path.join(DATA_DIR, "intervention_audit_log.parquet")
FEATURES_PATH = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
SCORES_PATH = os.path.join(DATA_DIR, "churn_scores_daily.parquet")
GROUND_TRUTH_PATH = os.path.join(DATA_DIR, "ground_truth.parquet")
SESSIONS_PATH = os.path.join(DATA_DIR, "sessions.parquet")
TRANSACTIONS_PATH = os.path.join(DATA_DIR, "transactions.parquet")
OUTCOMES_PATH = os.path.join(DATA_DIR, "intervention_outcomes.parquet")


def measure_outcomes() -> pd.DataFrame:
    """Measure post-intervention outcomes for every dispatched intervention.

    For each intervention in the audit log with status Sent/DryRun, this function
    checks the member's behavior in the 7, 14, and 30 days following the intervention
    and classifies the outcome.

    Returns:
        DataFrame with columns: audit_id, member_id, hashed_member_id,
        intervention_date, action_type, risk_tier, outcome_7d, outcome_14d,
        outcome_30d, re_engaged_date, payment_resolved_date, sessions_post_7d,
        sessions_post_14d, sessions_post_30d
    """
    # ---- Validate inputs ----
    for label, path in [
        ("Audit log", AUDIT_LOG_PATH),
        ("Sessions", SESSIONS_PATH),
        ("Transactions", TRANSACTIONS_PATH),
        ("Ground truth", GROUND_TRUTH_PATH),
    ]:
        if not os.path.exists(path):
            print(f"Error: {label} not found at {path}. Run the pipeline first.")
            sys.exit(1)

    # ---- Load data ----
    audit_df = pd.read_parquet(AUDIT_LOG_PATH)
    sessions_df = pd.read_parquet(SESSIONS_PATH)
    transactions_df = pd.read_parquet(TRANSACTIONS_PATH)
    gt_df = pd.read_parquet(GROUND_TRUTH_PATH)

    if audit_df.empty:
        print("No intervention records found in audit log.")
        return pd.DataFrame()

    # Filter to actionable interventions (Sent, DryRun — not Holdout/RateLimited)
    actionable = audit_df[audit_df["status"].isin(["Sent", "DryRun"])].copy()
    if actionable.empty:
        print("No sent/dry-run interventions found to measure outcomes for.")
        return pd.DataFrame()

    actionable["sent_at"] = pd.to_datetime(actionable["sent_at"])

    # Prepare session data: index by member_id and date
    sessions_df["session_date"] = pd.to_datetime(sessions_df["scheduled_at"]).dt.date
    session_attended = sessions_df[sessions_df["attended"] == True].copy()

    # Build a lookup: member_id → sorted list of attended session dates
    session_dates_by_member = (
        session_attended.groupby("member_id")["session_date"]
        .apply(lambda x: sorted(set(x)))
        .to_dict()
    )

    # Prepare transaction data: find successful payments after failed ones
    transactions_df["transaction_date"] = pd.to_datetime(transactions_df["transaction_date"]).dt.date
    paid_tx = transactions_df[
        (transactions_df["transaction_type"] == "Membership Fee") &
        (transactions_df["status"] == "Paid")
    ].copy()
    paid_dates_by_member = (
        paid_tx.groupby("member_id")["transaction_date"]
        .apply(lambda x: sorted(set(x)))
        .to_dict()
    )

    # Ground truth: who actually churned and when
    gt_lookup = {}
    for _, row in gt_df.iterrows():
        gt_lookup[row["member_id"]] = {
            "churned": row["churned"],
            "churn_date": pd.to_datetime(row["churn_date"]).date() if pd.notna(row["churn_date"]) else None,
        }

    # ---- Parse risk tier from the why_score field ----
    def extract_risk_tier(why_score: str) -> str:
        """Extract risk tier from audit log's why_score field (e.g. 'Score: 0.8234 | Tier: Critical')."""
        if not isinstance(why_score, str):
            return "Unknown"
        if "Tier: " in why_score:
            return why_score.split("Tier: ")[-1].strip()
        return "Unknown"

    # ---- Measure each intervention ----
    outcome_records = []

    for _, intervention in actionable.iterrows():
        audit_id = intervention["audit_id"]
        member_id = intervention["member_id"]
        hashed_id = intervention["hashed_member_id"]
        action_type = intervention["action_type"]
        sent_date = intervention["sent_at"].date()
        risk_tier = extract_risk_tier(intervention.get("why_score", ""))

        # Define measurement windows
        window_7d = sent_date + datetime.timedelta(days=7)
        window_14d = sent_date + datetime.timedelta(days=14)
        window_30d = sent_date + datetime.timedelta(days=30)

        # 1. Session re-engagement: did they attend any session in each window?
        member_sessions = session_dates_by_member.get(member_id, [])
        sessions_post_7d = sum(1 for d in member_sessions if sent_date < d <= window_7d)
        sessions_post_14d = sum(1 for d in member_sessions if sent_date < d <= window_14d)
        sessions_post_30d = sum(1 for d in member_sessions if sent_date < d <= window_30d)

        # First re-engagement date
        post_sessions = [d for d in member_sessions if d > sent_date]
        re_engaged_date = post_sessions[0] if post_sessions else None

        # 2. Payment resolution: did a successful payment follow the intervention?
        member_paid = paid_dates_by_member.get(member_id, [])
        post_payments = [d for d in member_paid if d > sent_date]
        payment_resolved_date = post_payments[0] if post_payments else None
        payment_resolved_within_30d = any(d <= window_30d for d in post_payments) if post_payments else False

        # 3. Churn check: is the member still active 30 days later?
        gt = gt_lookup.get(member_id, {"churned": False, "churn_date": None})
        member_churned = gt["churned"]
        churn_date = gt["churn_date"]

        churned_within_30d = (
            member_churned and churn_date is not None and
            sent_date < churn_date <= window_30d
        )

        # ---- Classify outcomes for each window ----
        def classify_outcome(window_end, sessions_in_window):
            """Classify a single measurement window."""
            if sessions_in_window > 0:
                return "re_engaged"
            if payment_resolved_date and payment_resolved_date <= window_end:
                return "payment_resolved"
            if member_churned and churn_date and churn_date <= window_end:
                return "churned"
            if not member_churned:
                return "still_active"
            return "no_response"

        outcome_7d = classify_outcome(window_7d, sessions_post_7d)
        outcome_14d = classify_outcome(window_14d, sessions_post_14d)
        outcome_30d = classify_outcome(window_30d, sessions_post_30d)

        outcome_records.append({
            "audit_id": audit_id,
            "member_id": member_id,
            "hashed_member_id": hashed_id,
            "intervention_date": sent_date,
            "action_type": action_type,
            "risk_tier": risk_tier,
            "outcome_7d": outcome_7d,
            "outcome_14d": outcome_14d,
            "outcome_30d": outcome_30d,
            "re_engaged_date": re_engaged_date,
            "payment_resolved_date": payment_resolved_date,
            "payment_resolved_within_30d": payment_resolved_within_30d,
            "sessions_post_7d": sessions_post_7d,
            "sessions_post_14d": sessions_post_14d,
            "sessions_post_30d": sessions_post_30d,
            "churned_within_30d": churned_within_30d,
        })

    outcomes_df = pd.DataFrame(outcome_records)
    return outcomes_df


def compute_conversion_rates(outcomes_df: pd.DataFrame) -> dict:
    """Compute aggregate conversion rates by channel and risk tier.

    Returns a dict of DataFrames keyed by grouping dimension.
    """
    if outcomes_df.empty:
        return {}

    rates = {}

    # Positive outcome = re_engaged or payment_resolved or still_active (not churned)
    outcomes_df = outcomes_df.copy()
    outcomes_df["positive_30d"] = outcomes_df["outcome_30d"].isin(
        ["re_engaged", "payment_resolved", "still_active"]
    )

    # By channel
    by_channel = outcomes_df.groupby("action_type").agg(
        total=("audit_id", "count"),
        re_engaged=("outcome_30d", lambda x: (x == "re_engaged").sum()),
        payment_resolved=("outcome_30d", lambda x: (x == "payment_resolved").sum()),
        churned=("outcome_30d", lambda x: (x == "churned").sum()),
        positive_rate=("positive_30d", "mean"),
    ).round(3)
    rates["by_channel"] = by_channel

    # By risk tier
    by_tier = outcomes_df.groupby("risk_tier").agg(
        total=("audit_id", "count"),
        re_engaged=("outcome_30d", lambda x: (x == "re_engaged").sum()),
        churned=("outcome_30d", lambda x: (x == "churned").sum()),
        positive_rate=("positive_30d", "mean"),
    ).round(3)
    rates["by_tier"] = by_tier

    # By channel × tier
    by_channel_tier = outcomes_df.groupby(["action_type", "risk_tier"]).agg(
        total=("audit_id", "count"),
        positive_rate=("positive_30d", "mean"),
    ).round(3)
    rates["by_channel_tier"] = by_channel_tier

    return rates


def get_channel_effectiveness() -> dict[str, float]:
    """Load historical outcomes and return 30-day positive rate by channel.

    Used by the adaptive intervention router to decide escalation thresholds.
    Returns a dict like {"Email": 0.45, "SMS": 0.38, "Call": 0.62}.
    """
    if not os.path.exists(OUTCOMES_PATH):
        return {}

    outcomes_df = pd.read_parquet(OUTCOMES_PATH)
    if outcomes_df.empty:
        return {}

    outcomes_df["positive_30d"] = outcomes_df["outcome_30d"].isin(
        ["re_engaged", "payment_resolved", "still_active"]
    )

    rates = outcomes_df.groupby("action_type")["positive_30d"].mean().to_dict()
    return rates


def run_outcome_tracking():
    """Main entry point: measure outcomes, print conversion rates, save to parquet."""
    print("=" * 60)
    print("INTERVENTION OUTCOME TRACKER")
    print("=" * 60)

    outcomes_df = measure_outcomes()

    if outcomes_df.empty:
        print("No outcomes to measure. Exiting.")
        return

    # ---- Summary Report ----
    print(f"\nMeasured outcomes for {len(outcomes_df):,} interventions.")

    print("\n" + "-" * 60)
    print("30-DAY OUTCOME DISTRIBUTION")
    print("-" * 60)
    outcome_counts = outcomes_df["outcome_30d"].value_counts()
    total = len(outcomes_df)
    for outcome, count in outcome_counts.items():
        pct = (count / total) * 100
        bar = "█" * int(pct / 2)
        print(f"  {outcome:22s}  {count:5,d}  ({pct:5.1f}%)  {bar}")

    # Conversion rates
    rates = compute_conversion_rates(outcomes_df)

    if "by_channel" in rates:
        print("\n" + "-" * 60)
        print("CONVERSION RATE BY CHANNEL (30-day positive outcome)")
        print("-" * 60)
        print(rates["by_channel"].to_string())

    if "by_tier" in rates:
        print("\n" + "-" * 60)
        print("CONVERSION RATE BY RISK TIER (30-day positive outcome)")
        print("-" * 60)
        print(rates["by_tier"].to_string())

    # ---- Save ----
    outcomes_df.to_parquet(OUTCOMES_PATH, index=False)
    print(f"\nSaved {len(outcomes_df):,} outcome records to: {OUTCOMES_PATH}")

    print("=" * 60)
    print("OUTCOME TRACKING COMPLETED")
    print("=" * 60)

    return outcomes_df


if __name__ == "__main__":
    run_outcome_tracking()
