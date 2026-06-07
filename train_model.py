"""
Rolling-Window Model Trainer  (Phase 4 core)
============================================
The churn model must NOT be static. As the business grows the model is retrained
continuously, and — critically — on a rolling *time* window rather than all history.

    DESIGN PRINCIPLE (top priority): range of TIME > range of DATA.
    A model trained on 1970–2026 is skewed for 2027; a model trained on a consistent
    trailing 2–3 years tracks the current business. So training always filters to
    `date_day >= as_of - ROLLING_TRAIN_WINDOW_MONTHS`, regardless of how much older
    data exists. More history is deliberately discarded.

This module is the programmatic, automatable equivalent of train_evaluate.ipynb:
trains XGBoost (class-weighted) + isotonic calibration, then saves both the live model
and a timestamped, versioned copy, and appends a row to the model registry.

Outputs:
  models/churn_model_pipeline.joblib                 (live model)
  models/churn_model_pipeline_{version}.joblib       (versioned snapshot)
  models/model_registry.parquet                      (training history)
"""

import os
import datetime
import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import roc_auc_score, average_precision_score
from xgboost import XGBClassifier

DATA_DIR = "./data"
MODELS_DIR = "./models"
FEATURES_PATH = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
LIVE_MODEL_PATH = os.path.join(MODELS_DIR, "churn_model_pipeline.joblib")
REGISTRY_PATH = os.path.join(MODELS_DIR, "model_registry.parquet")

# --- The core knob: rolling training window in MONTHS (time range, not row count). ---
ROLLING_TRAIN_WINDOW_MONTHS = 24
# Exclude the most recent days whose 14-day churn label hasn't fully matured yet.
LABEL_MATURITY_DAYS = 14
# Fraction of the (chronological) window used for training; remainder calibrates.
TRAIN_SPLIT_FRACTION = 0.8

CATEGORICAL_COLS = ["gender", "home_studio_id", "membership_tier"]
NUMERIC_COLS = [
    "age", "monthly_price", "tenure_days", "sessions_booked_7d", "sessions_booked_30d",
    "sessions_attended_7d", "sessions_attended_30d", "attendance_rate_7d", "attendance_rate_30d",
    "avg_sauna_temp_30d", "days_since_last_session", "retail_spend_30d", "failed_payments_count_30d",
    "app_logins_7d", "app_logins_30d", "metric_views_30d", "coach_chat_count_30d",
    "emails_sent_30d", "emails_opened_30d", "emails_clicked_30d", "email_open_rate_30d",
]
BOOLEAN_COLS = ["last_recurring_payment_failed", "has_cancellation_query_30d"]
FEATURE_COLS = CATEGORICAL_COLS + NUMERIC_COLS + BOOLEAN_COLS
TARGET_COL = "is_churned_14d"


def _build_pipeline(scale_pos_weight: float) -> Pipeline:
    """XGBoost pipeline; StandardScaler preserves NaN and XGBoost handles it natively."""
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERIC_COLS),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_COLS),
            ("bool", "passthrough", BOOLEAN_COLS),
        ]
    )
    return Pipeline([
        ("preprocessor", preprocessor),
        ("classifier", XGBClassifier(
            n_estimators=150, learning_rate=0.08, max_depth=5,
            subsample=0.8, colsample_bytree=0.8, scale_pos_weight=scale_pos_weight,
            random_state=42, eval_metric="logloss",
        )),
    ])


def load_training_window(window_months: int = ROLLING_TRAIN_WINDOW_MONTHS,
                         features_path: str = FEATURES_PATH):
    """Load the feature table and clip to the trailing `window_months` of MATURE-label rows.

    Returns (df_window, meta) where meta records the exact time window used.
    """
    df = pd.read_parquet(features_path)
    df["date_day"] = pd.to_datetime(df["date_day"])
    as_of = df["date_day"].max()

    label_cutoff = as_of - pd.Timedelta(days=LABEL_MATURITY_DAYS)
    window_start = as_of - pd.DateOffset(months=window_months)

    full_min = df["date_day"].min()
    win = df[(df["date_day"] >= window_start) & (df["date_day"] <= label_cutoff)].copy()

    meta = {
        "as_of": as_of,
        "window_start": win["date_day"].min() if not win.empty else window_start,
        "window_end": win["date_day"].max() if not win.empty else label_cutoff,
        "window_months": window_months,
        "rows_in_window": len(win),
        "rows_discarded_as_old": int((df["date_day"] < window_start).sum()),
        "oldest_available": full_min,
    }
    return win, meta


def train_and_save(window_months: int = ROLLING_TRAIN_WINDOW_MONTHS, trigger: str = "manual") -> dict:
    """Retrain on the rolling window, calibrate, save live + versioned model, log to registry."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    win, meta = load_training_window(window_months)
    if win.empty:
        raise ValueError("No rows in the training window — check the feature table / window size.")

    # Chronological split inside the window (never random — rows are a daily panel).
    split_date = win["date_day"].quantile(TRAIN_SPLIT_FRACTION)
    train_df = win[win["date_day"] < split_date]
    val_df = win[win["date_day"] >= split_date]
    if val_df.empty or train_df.empty:
        # Degenerate window; fall back to a simple 80/20 row split by time order.
        win_sorted = win.sort_values("date_day")
        cut = int(len(win_sorted) * TRAIN_SPLIT_FRACTION)
        train_df, val_df = win_sorted.iloc[:cut], win_sorted.iloc[cut:]

    X_train, y_train = train_df[FEATURE_COLS], train_df[TARGET_COL].astype(int)
    X_val, y_val = val_df[FEATURE_COLS], val_df[TARGET_COL].astype(int)

    neg, pos = int((y_train == 0).sum()), int((y_train == 1).sum())
    scale_pos_weight = (neg / pos) if pos > 0 else 1.0

    pipeline = _build_pipeline(scale_pos_weight)
    pipeline.fit(X_train, y_train)

    # Isotonic calibration on the held-out (recent) slice so probabilities stay honest.
    calibrated = CalibratedClassifierCV(FrozenEstimator(pipeline), method="isotonic")
    calibrated.fit(X_val, y_val)

    val_probs = calibrated.predict_proba(X_val)[:, 1]
    val_auc = float(roc_auc_score(y_val, val_probs)) if y_val.nunique() > 1 else float("nan")
    val_pr_auc = float(average_precision_score(y_val, val_probs)) if y_val.nunique() > 1 else float("nan")

    version = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    versioned_path = os.path.join(MODELS_DIR, f"churn_model_pipeline_{version}.joblib")
    joblib.dump(calibrated, LIVE_MODEL_PATH)
    joblib.dump(calibrated, versioned_path)

    record = {
        "version_id": version,
        "trained_at": datetime.datetime.now(),
        "trigger": trigger,
        "train_window_start": pd.Timestamp(meta["window_start"]).date().isoformat(),
        "train_window_end": pd.Timestamp(meta["window_end"]).date().isoformat(),
        "window_months": window_months,
        "train_rows": len(train_df),
        "val_rows": len(val_df),
        "rows_discarded_as_old": meta["rows_discarded_as_old"],
        "scale_pos_weight": round(scale_pos_weight, 1),
        "val_auc": round(val_auc, 4),
        "val_pr_auc": round(val_pr_auc, 4),
        "model_path": versioned_path,
    }
    _append_registry(record)
    return record


def _append_registry(record: dict):
    df_new = pd.DataFrame([record])
    if os.path.exists(REGISTRY_PATH):
        existing = pd.read_parquet(REGISTRY_PATH)
        df_new = pd.concat([existing, df_new], ignore_index=True)
    df_new.to_parquet(REGISTRY_PATH, index=False)


def load_registry() -> pd.DataFrame:
    if os.path.exists(REGISTRY_PATH):
        return pd.read_parquet(REGISTRY_PATH).sort_values("trained_at", ascending=False).reset_index(drop=True)
    return pd.DataFrame()


def current_model_info() -> dict:
    """Most recent registry record, or {} if the model was trained outside this module."""
    reg = load_registry()
    return reg.iloc[0].to_dict() if not reg.empty else {}


def main():
    print("=" * 60)
    print("ROLLING-WINDOW MODEL RETRAIN")
    print(f"Window: trailing {ROLLING_TRAIN_WINDOW_MONTHS} months (time range > data range)")
    print("=" * 60)
    rec = train_and_save(trigger="manual")
    print(f"\nTrained model version {rec['version_id']}")
    print(f"  Training window : {rec['train_window_start']} -> {rec['train_window_end']} ({rec['window_months']} mo)")
    print(f"  Rows train/val  : {rec['train_rows']:,} / {rec['val_rows']:,}")
    print(f"  Old rows dropped: {rec['rows_discarded_as_old']:,}  (deliberately excluded)")
    print(f"  Val AUC / PR-AUC: {rec['val_auc']} / {rec['val_pr_auc']}")
    print(f"  Saved           : {LIVE_MODEL_PATH}  +  {rec['model_path']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
