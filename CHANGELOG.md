# HOTWORX Churn Demo — Engineering Changelog

Record of the Phase 1–3 review, fixes, and retrain. Date: 2026-06-06. All data is SYNTHETIC.

---

## 1. Phase 1 & 2 review — bugs found and fixed

### 🔴 CRITICAL — `sudden_drop` cohort missing its defining signal
- **Found:** 263/482 (55%) of `sudden_drop` members had **no failed-payment record**, even though that cohort's whole premise is "billing fails → cancel 14 days later." Cause: billing was generated monthly from `join_date`, and a failure was only stamped if a monthly cycle happened to land in the final 14 days. The integrity check only asserted a *global* `len(failed_tx) > 0`, so it passed and masked the gap.
- **Fix (`generate_synthetic_data.py`):** explicitly inject a guaranteed `Failed` charge at `churn_date − 14` for every churned `sudden_drop` member; stop normal paid billing at that point. Replaced the global assertion with **per-member coverage ≥ 99%** (now prints the % and fails loudly on regression). Removed unused `bill_count`.
- **Verified:** coverage 482/482 (100%); all 482 carry the signal downstream in `fct` (`failed_payments_count_30d` / `last_recurring_payment_failed`).

### 🟠 HIGH — `attendance_rate` conflated "didn't book" with "booked but skipped"
- **Found:** `attendance_rate_7d/30d` returned `0.0` when there were 0 bookings — identical to a real no-show (also `0.0`). 8,238 rows were ambiguous.
- **Fix (`fct_member_features_daily.sql`):** return `NULL` (not `0.0`) when no bookings in the window. Inactive is now distinguishable from 0%.

### 🟠 HIGH — Phase 3 train/test split (checked, no fix needed)
- The notebook already uses a **chronological** split (train `<2025-09-01`, val, test `≥2026-01-01`), so the random-split leakage risk was never present. ✅

### 🟡 MEDIUM — "secure identity mapping" was plaintext PII + dead PII test
- **Found:** `int_member_identity.parquet` stores `name/email/phone` in cleartext next to the hash, written unencrypted, salt hardcoded in source. `run_pipeline.py` printed it as "secure". Test C's value-leakage query was a tautology that never asserted anything.
- **Fix:** honest `PLAINTEXT PII — synthetic/demo only` warning + Phase-5 TODOs (encrypt at rest, least-privilege, salt → secrets manager) in `run_pipeline.py` and `int_member_identity.sql`. Rewrote Test C to do a real **column-level AND value-level** leakage assertion (passes).

---

## 2. Low-severity cleanups (Phase 2)

All in `fct_member_features_daily.sql`:
- **`'login'` dead reference** → matches only `'open_app'` (the event the source actually emits).
- **Magic dates de-duplicated** → a `config` CTE derives the observation horizon (`as_of_date`) from `MAX` of the event dates instead of two hardcoded `2026-06-0x` literals. (Row count moved 2,041,157 → 2,037,425; snapshot is now the true last data day `2026-05-31`.)
- **`email_open_rate_30d`** → `NULL` when no emails sent, consistent with the attendance fix.

---

## 3. Phase 3 retrain (`train_evaluate.ipynb`)

### NaN handling (required by the NULL features above)
- `StandardScaler` preserves NaN but `LogisticRegression` rejects it. Split preprocessing per-model:
  - **XGBoost:** native NaN handling (scaler only).
  - **LogisticRegression:** `SimpleImputer(strategy='constant', fill_value=-1.0)` sentinel (outside the natural [0,1] / non-negative ranges) so "missing" stays separable.

### Class imbalance + calibration (Note 2)
- Added `scale_pos_weight = neg/pos ≈ 185.4` (auto-computed) to XGBoost; `class_weight='balanced'` to the LR baseline for parity.
- **Isotonic recalibration** on the validation set via `CalibratedClassifierCV(FrozenEstimator(xgb_pipeline), method='isotonic')`. Class weighting inflates raw probabilities; isotonic is monotonic so it preserves ranking (AUC/PR-AUC) while restoring true-probability meaning that the downstream risk tiers depend on.
- **Serialized the calibrated model** to `models/churn_model_pipeline.joblib`. Feature importances still read from the underlying (frozen, unmodified) `xgb_pipeline`.
- Added **PR-AUC (Average Precision)** as the honest headline metric for this imbalance.

---

## 4. Final results (corrected data, calibrated + class-weighted)

| Metric | Notes |
|---|---|
| XGBoost AUC-ROC | 0.9650 (near-saturated, imbalance-blind) |
| **XGBoost PR-AUC (AP)** | **0.7126** vs LR 0.6255 — the real signal; AUC-ROC hid this gap |
| Churn-class @0.35 | precision 0.60 / recall 0.75 / F1 0.67 |
| Re-scored risk tiers (3,740 active members) | **3,579 Low / 55 Medium / 91 High / 15 Critical**, mean prob 0.028 — proves calibration kept tiers sane (would be ~all-Critical without it) |

EDA (`demo_visualization.ipynb`) re-run: billing-failure→cancel delta now **482 records, mean 14.0 days, std 0.0** — a clean spike demonstrating the cohort design. All 9 plots refreshed.

---

## 5. Phase 4 review — dashboard (`dashboard.py`) & intervention router (`interventions.py`)

Reviewed both; fixed the three highest-severity issues (each verified by running the router).

### 🔴 CRITICAL — send kill-switch was non-functional + sends without an audit trail (fixed)
- `check_global_rate_limit` only read the on-disk audit log, but in-run sends are persisted at the
  end of the loop — so within a single run the counter never moved and the `GLOBAL_LIMIT_HOURLY=50`
  kill switch could not trip (empirically: **136 live attempts processed under a limit of 50**). And
  because audit was saved only after the loop, a mid-loop `raise` discarded the record of sends
  already made.
- **Fix:** track an in-run `in_run_sent` counter; check `prior_on_disk + in_run_sent` against the
  limit; on trip, `break` (not `raise`) so audit/queue flush first, then re-raise loudly.
- **Verified:** clean-state LIVE run now halts at exactly **50/50**, raises `RuntimeError`, and the
  audit log persisted all 50 `Sent` rows despite the raise (no send without a record). Dry-run exits 0.

### 🔴 HIGH — row-level security via string `.replace()` + shared cached connection (fixed)
- RLS was enforced by rewriting query text (`query.replace("features","secure_features")...`) —
  brittle and bypassable if any query contained those substrings. And `@st.cache_resource` shared
  ONE DuckDB connection across all sessions, so concurrent GMs raced on the per-user `secure_*` views
  and could be served each other's studio data.
- **Fix:** per-session connection in `st.session_state`; base views (`features`/`identity`/`scores`)
  are defined already-scoped to the user's studio, so every query is row-secured with no text
  rewriting. Studio validated (`[A-Za-z0-9_]+`) before inlining (DuckDB can't bind params in
  `CREATE VIEW`). Verified isolation: a GM sees 492 of 5000 members.

### 🔴 HIGH — A/B panel showed an effect the system can't produce + latent crash (fixed)
- The A/B tab compared `ground_truth.churned` across holdout/treatment, but interventions are
  dry-run and synthetic churn is pre-determined, so any "lift" is spurious; it also fabricated
  23%-vs-12% numbers when empty. Separately it referenced `merged_ab["status_x"]`, but the merge
  yields `status` (ground_truth has no `status` column) — a guaranteed `KeyError` on real data.
- **Fix:** prominent "illustrative wireframe — not a measured result" banner; placeholder values are
  explicitly labelled PLACEHOLDER; computed values captioned as ~random; the A/B view now respects
  GM studio scoping; `status_x` → `status`.

### Not changed at review time (most addressed in §6)
- ✅ Plaintext credentials in `dashboard.py` → now hashed + externalized (see §6).
- ✅ Perf: `check_member_rate_limit` re-parsed the whole audit parquet per member → audit now read once (§6).
- ✅ `action_id` could collide within the same second → now uses a per-run uuid prefix (§6). (Queue/audit compaction + a dedicated `run_id` column still deferred.)
- Still as-is (benign): `stats["sent"]` counts Pending calls (label reads "Queued/Sent"); views re-created per query; holdout checked after rate-limit.

## 6. Phase 5 hardening (in progress)

Took on the highest-value deferred items from the Phase 4 review.

### Credentials out of source + hashed (`auth.py`, `dashboard.py`, `.gitignore`)
- Removed the hardcoded plaintext `USER_ACCOUNTS` dict. Accounts now load via `auth.load_user_accounts()`:
  `dashboard_users.json` (gitignored) → `DASHBOARD_USERS_JSON` env → demo fallback hashed in-memory from
  `DASHBOARD_ADMIN_PW` / `DASHBOARD_GM_PW` (overridable defaults).
- Passwords are stored/compared as **PBKDF2-HMAC-SHA256** (240k iterations, per-user random salt) with a
  **constant-time** `hmac.compare_digest`. `dashboard_users.json` added to `.gitignore`.
- Verified: account records carry only `password_hash` (no plaintext); correct password verifies, wrong rejected.

### Router perf — audit log read once (`interventions.py`)
- `check_member_rate_limit` re-read/re-parsed the whole audit parquet per member (O(members × log size)). The
  "messaged in the last 7 days" set is now precomputed **once** from the already-loaded audit log; the
  per-member check is a set lookup. Dry-run output is byte-identical to before the change.

### Collision-proof intervention IDs (`interventions.py`)
- `action_id`/`audit_id` were `AC{epoch_secs}{idx}` — collidable if two runs start in the same second. Now
  `AC{run_id}{idx}` with a per-run `uuid4` prefix. Verified all `action_id`s unique after a run.

### Still deferred (genuine infra, not started)
- Encrypt the identity mapping at rest + least-privilege access; move the hashing salt to a secrets manager
  (the `int_member_identity` TODOs).
- Queue/audit retention/compaction + a dedicated `run_id` column for run-level grouping (IDs embed it for now).

## 7. Still open / future work
- `precision@10%` reads ~14% structurally (positives < 2% of rows ≪ the 10% bucket). **Retire it from the headline; quote PR-AUC.**
- `avg_sauna_temp_30d` still uses `0.0` when no attended sessions — acceptable because real temps are 120–130°F so `0.0` is an unambiguous sentinel (unlike rates).
- Phase 5: encrypt the identity mapping at rest, least-privilege access, move hashing salt to a secrets manager (TODOs in code).
- Optional modeling: hyperparameter tuning; `scale_pos_weight` sweep; threshold tuning per risk tier.

## How to reproduce
```
.venv/bin/python generate_synthetic_data.py          # Phase 1: synthetic data + integrity checks
.venv/bin/python run_pipeline.py                     # Phase 2: DuckDB feature pipeline + DQ checks
.venv/bin/jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=600 train_evaluate.ipynb   # Phase 3: retrain
.venv/bin/python score_members.py --top-k 5          # score active members + top-K report
.venv/bin/jupyter nbconvert --to notebook --execute --inplace demo_visualization.ipynb                                 # refresh EDA plots
.venv/bin/python interventions.py                    # Phase 4: rules engine (dry-run; set INTERVENTIONS_LIVE=true to send)
.venv/bin/streamlit run dashboard.py                 # Phase 4: dashboard (log in via USER_ACCOUNTS)
```
