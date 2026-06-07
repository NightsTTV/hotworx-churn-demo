"""
Model Monitoring & Drift Detection  (Phase 4)
=============================================
Keeps the churn model honest over time and decides WHEN to retrain:

  1. Calibration check  : predicted churn prob vs. actual churn rate by decile;
                          alerts when |predicted - actual| > 15% in any decile.
  2. Drift detection    : Population Stability Index (PSI) per key feature, comparing
                          the model's training-window distribution to the most recent
                          window. PSI >0.1 moderate, >0.2 significant.
  3. Auto-retrain       : if calibration or drift breaches threshold, triggers
                          train_model.train_and_save() — which retrains on the rolling
                          TIME window (trailing N months), saves a timestamped model, and
                          logs to the registry.

Run:
  python model_monitor.py                 # evaluate + write health reports
  python model_monitor.py --auto-retrain  # ...and retrain if drift/calibration breached
  python model_monitor.py --simulate-drift# perturb the recent window to prove detection fires
  python model_monitor.py --retrain       # force a rolling-window retrain now

Outputs:
  data/model_health_calibration.parquet
  data/model_health_drift.parquet
  data/model_monitor_log.parquet
"""

import os
import sys
import argparse
import datetime
import joblib
import numpy as np
import pandas as pd

import train_model as tm

DATA_DIR = "./data"
FEATURES_PATH = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
LIVE_MODEL_PATH = tm.LIVE_MODEL_PATH

CALIBRATION_PATH = os.path.join(DATA_DIR, "model_health_calibration.parquet")
DRIFT_PATH = os.path.join(DATA_DIR, "model_health_drift.parquet")
MONITOR_LOG_PATH = os.path.join(DATA_DIR, "model_monitor_log.parquet")

# Key features watched for distribution drift.
DRIFT_FEATURES = [
    "sessions_attended_30d", "days_since_last_session", "app_logins_30d",
    "failed_payments_count_30d", "attendance_rate_30d", "retail_spend_30d",
    "coach_chat_count_30d", "monthly_price",
]

CALIB_DEV_RETRAIN = 0.15     # 15% decile deviation
PSI_MODERATE = 0.10
PSI_SIGNIFICANT = 0.20
PSI_RETRAIN = 0.25
RECENT_WINDOW_DAYS = 30
CALIB_WINDOW_DAYS = 90


# ==============================================================================
# CALIBRATION
# ==============================================================================
def compute_calibration(n_bins: int = 10) -> tuple[pd.DataFrame, float]:
    """Decile calibration: mean predicted prob vs. actual churn rate on a recent,
    label-mature window. Returns (table, max_abs_deviation)."""
    model = joblib.load(LIVE_MODEL_PATH)
    df = pd.read_parquet(FEATURES_PATH)
    df["date_day"] = pd.to_datetime(df["date_day"])
    as_of = df["date_day"].max()

    mature = df[df["date_day"] <= as_of - pd.Timedelta(days=tm.LABEL_MATURITY_DAYS)]
    recent = mature[mature["date_day"] > as_of - pd.Timedelta(days=CALIB_WINDOW_DAYS + tm.LABEL_MATURITY_DAYS)]
    if recent.empty:
        recent = mature.tail(200_000)

    probs = model.predict_proba(recent[tm.FEATURE_COLS])[:, 1]
    actual = recent[tm.TARGET_COL].astype(int).to_numpy()

    eval_df = pd.DataFrame({"pred": probs, "actual": actual})
    eval_df["decile"] = pd.qcut(eval_df["pred"].rank(method="first"), n_bins, labels=False)
    table = eval_df.groupby("decile").agg(
        count=("actual", "size"),
        avg_predicted=("pred", "mean"),
        actual_rate=("actual", "mean"),
    ).reset_index()
    table["abs_deviation"] = (table["avg_predicted"] - table["actual_rate"]).abs()
    table = table.round(4)
    return table, float(table["abs_deviation"].max())


# ==============================================================================
# DRIFT (PSI)
# ==============================================================================
def psi(reference: pd.Series, current: pd.Series, bins: int = 10) -> float:
    """Population Stability Index between a reference and current distribution."""
    ref = reference.dropna().to_numpy()
    cur = current.dropna().to_numpy()
    if len(ref) < 10 or len(cur) < 10:
        return 0.0
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    ref_pct = np.histogram(ref, edges)[0] / len(ref)
    cur_pct = np.histogram(cur, edges)[0] / len(cur)
    eps = 1e-6
    ref_pct = np.clip(ref_pct, eps, None)
    cur_pct = np.clip(cur_pct, eps, None)
    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


def _severity(p: float) -> str:
    if p >= PSI_SIGNIFICANT:
        return "Significant"
    if p >= PSI_MODERATE:
        return "Moderate"
    return "Stable"


def _reference_and_current(df: pd.DataFrame):
    """Reference = the live model's training window; current = most recent window."""
    as_of = df["date_day"].max()
    cur = df[df["date_day"] > as_of - pd.Timedelta(days=RECENT_WINDOW_DAYS)]

    info = tm.current_model_info()
    if info and info.get("train_window_start") and info.get("train_window_end"):
        start = pd.Timestamp(info["train_window_start"])
        end = pd.Timestamp(info["train_window_end"])
        ref = df[(df["date_day"] >= start) & (df["date_day"] <= end)]
    else:
        ref = df[(df["date_day"] >= as_of - pd.DateOffset(months=12)) &
                 (df["date_day"] <= as_of - pd.Timedelta(days=RECENT_WINDOW_DAYS))]
    return ref, cur


def compute_feature_drift(perturb: bool = False) -> tuple[pd.DataFrame, float]:
    """PSI per watched feature (reference training window vs. recent window).
    If `perturb`, distort the recent window to demonstrate detection firing."""
    df = pd.read_parquet(FEATURES_PATH)
    df["date_day"] = pd.to_datetime(df["date_day"])
    ref, cur = _reference_and_current(df)
    cur = cur.copy()

    if perturb:
        # Simulate a behavioural shift: members attending far less, going dormant longer,
        # logging in less, with more payment failures.
        if "sessions_attended_30d" in cur:
            cur["sessions_attended_30d"] = cur["sessions_attended_30d"] * 0.3
        if "days_since_last_session" in cur:
            cur["days_since_last_session"] = cur["days_since_last_session"] + 25
        if "app_logins_30d" in cur:
            cur["app_logins_30d"] = cur["app_logins_30d"] * 0.4
        if "failed_payments_count_30d" in cur:
            cur["failed_payments_count_30d"] = cur["failed_payments_count_30d"] + 1

    rows = []
    for feat in DRIFT_FEATURES:
        if feat not in df.columns:
            continue
        p = round(psi(ref[feat], cur[feat]), 4)
        rows.append({"feature": feat, "psi": p, "severity": _severity(p)})
    drift = pd.DataFrame(rows).sort_values("psi", ascending=False).reset_index(drop=True)
    return drift, float(drift["psi"].max()) if not drift.empty else 0.0


# ==============================================================================
# EVALUATE + DECIDE
# ==============================================================================
def evaluate(perturb: bool = False) -> dict:
    if not os.path.exists(LIVE_MODEL_PATH):
        print("No live model found. Run train_model.py first.")
        sys.exit(1)

    calib, calib_max_dev = compute_calibration()
    drift, max_psi = compute_feature_drift(perturb=perturb)

    reasons = []
    if calib_max_dev >= CALIB_DEV_RETRAIN:
        reasons.append(f"calibration deviation {calib_max_dev:.1%} >= {CALIB_DEV_RETRAIN:.0%}")
    if max_psi >= PSI_RETRAIN:
        worst = drift.iloc[0]
        reasons.append(f"feature drift PSI {max_psi:.2f} >= {PSI_RETRAIN} ({worst['feature']})")
    needs_retrain = len(reasons) > 0

    calib.to_parquet(CALIBRATION_PATH, index=False)
    drift.to_parquet(DRIFT_PATH, index=False)
    _log_monitor(calib_max_dev, max_psi, needs_retrain, reasons, perturb)

    return {
        "calibration": calib,
        "calib_max_dev": calib_max_dev,
        "drift": drift,
        "max_psi": max_psi,
        "needs_retrain": needs_retrain,
        "reasons": reasons,
        "perturbed": perturb,
    }


def _log_monitor(calib_dev, max_psi, needs_retrain, reasons, perturbed):
    rec = {
        "checked_at": datetime.datetime.now(),
        "calib_max_dev": round(calib_dev, 4),
        "max_psi": round(max_psi, 4),
        "needs_retrain": needs_retrain,
        "reasons": "; ".join(reasons) if reasons else "none",
        "mode": "simulate-drift" if perturbed else "live",
    }
    df_new = pd.DataFrame([rec])
    if os.path.exists(MONITOR_LOG_PATH):
        df_new = pd.concat([pd.read_parquet(MONITOR_LOG_PATH), df_new], ignore_index=True)
    df_new.to_parquet(MONITOR_LOG_PATH, index=False)


def _print_report(result: dict):
    print("\n" + "-" * 60)
    print("CALIBRATION (predicted vs. actual by decile)")
    print("-" * 60)
    print(result["calibration"].to_string(index=False))
    print(f"  Max decile deviation: {result['calib_max_dev']:.1%}  (threshold {CALIB_DEV_RETRAIN:.0%})")

    print("\n" + "-" * 60)
    print("FEATURE DRIFT (PSI: training window vs. recent window)")
    print("-" * 60)
    print(result["drift"].to_string(index=False))
    print(f"  Max PSI: {result['max_psi']:.3f}  (retrain at {PSI_RETRAIN})")

    print("\n" + "=" * 60)
    if result["needs_retrain"]:
        print("RESULT: RETRAIN RECOMMENDED  ->  " + "; ".join(result["reasons"]))
    else:
        print("RESULT: model healthy — no retrain needed.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Churn model monitoring & drift detection.")
    parser.add_argument("--auto-retrain", action="store_true", help="Retrain if drift/calibration breached.")
    parser.add_argument("--simulate-drift", action="store_true", help="Perturb the recent window to prove detection fires.")
    parser.add_argument("--retrain", action="store_true", help="Force a rolling-window retrain now.")
    args = parser.parse_args()

    print("=" * 60)
    print("MODEL MONITOR & DRIFT DETECTION")
    print("=" * 60)

    if args.retrain:
        rec = tm.train_and_save(trigger="manual-force")
        print(f"Forced retrain complete: version {rec['version_id']} "
              f"(window {rec['train_window_start']} -> {rec['train_window_end']})")
        return

    result = evaluate(perturb=args.simulate_drift)
    _print_report(result)

    if result["needs_retrain"] and args.auto_retrain:
        print("\nAuto-retrain triggered...")
        rec = tm.train_and_save(trigger="auto-drift")
        print(f"  Retrained version {rec['version_id']} on rolling window "
              f"{rec['train_window_start']} -> {rec['train_window_end']} "
              f"(val AUC {rec['val_auc']}, PR-AUC {rec['val_pr_auc']}).")
    elif result["needs_retrain"]:
        print("\n(Re-run with --auto-retrain to retrain automatically.)")


if __name__ == "__main__":
    main()
