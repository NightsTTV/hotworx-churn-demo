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

## CRM Tracker — Phase 3: Revenue Impact Attribution

New `revenue_metrics.py` + an Admin "Revenue Impact" dashboard view.

- **Model-based attribution (honest):** because interventions are dispatched as of the latest data
  date, there's no *forward* window for `re_engaged`/`payment_resolved` to fire — so "saved" is an
  expected-value estimate, not a naive outcome count. `Saved MRR = Σ(churn_probability × tier_price)
  × effectiveness`, segmented (retention 25% vs. win-back reactivation 8% — the only two assumptions;
  everything else data-driven). `confirmed_reengaged` is tracked separately for when real forward data
  accrues. Headline `MRR At Risk` ($38,870/mo) is assumption-free.
- **Metrics:** MRR-at-risk, Saved/Lost MRR, net monthly impact, LTV impact (× 9-mo observed lifetime),
  per-channel ROI (Email $0.01 / SMS $0.05 / Call $5.00), and **Kaplan-Meier cohort retention** (proper
  right-censoring; 78.2% @ 12 mo). Outputs `data/revenue_studio_leaderboard.parquet` + `revenue_cohort_retention.parquet`.
- **Dashboard:** Admin-only "Revenue Impact" view — KPI cards, retention curve, channel-ROI table,
  studio leaderboard (gradient), and a **franchise PDF export** (matplotlib PdfPages — no new dependency).
- Verified: `revenue_metrics.py` runs (ROI 470×, est. ~51 members saved/mo), all dashboard data
  functions return expected shapes, PDF renders (~45 KB), everything compiles.

## CRM Tracker — Phase 4: Model Monitoring & Drift Detection

New `train_model.py` (rolling-window retrain core) + `model_monitor.py` + an Admin "Model Health" dashboard view.

- **TOP PRIORITY — rolling TIME window, not all history.** `train_model.py` always trains on
  `date_day >= as_of - ROLLING_TRAIN_WINDOW_MONTHS` (default **24 mo**); older data is deliberately
  discarded (range of *time* > range of *data*). Verified: trained on 2024-05-31→2026-05-17, **dropped
  100,680 older rows**, val AUC 0.98 / PR-AUC 0.79. Excludes the last 14 days (immature labels),
  chronological train/calibrate split, XGBoost + isotonic calibration — same recipe as the notebook,
  now programmatic and automatable.
- **Versioning + registry:** saves live `churn_model_pipeline.joblib` **and** a timestamped
  `churn_model_pipeline_{version}.joblib`; appends `models/model_registry.parquet` (window dates,
  rows, trigger, val AUC/PR-AUC).
- **`model_monitor.py`:**
  - *Calibration check* — predicted vs. actual churn by decile; alert if any decile |dev| > 15%
    (live: max 0.1% — well-calibrated).
  - *Drift detection* — PSI per key feature (training window vs. recent 30 days); >0.1 moderate,
    >0.2 significant. **Verified it fires:** `--simulate-drift` perturbs the recent window →
    PSI 13.1 / 10.8 / 10.0 → "RETRAIN RECOMMENDED."
  - *Auto-retrain* — `--auto-retrain` triggers `train_model.train_and_save(trigger="auto-drift")`
    when breached (verified: produced a new registry version). Also `--retrain` to force.
  - Writes `model_health_calibration.parquet`, `model_health_drift.parquet`, `model_monitor_log.parquet`.
- **Dashboard "Model Health" view (Admin):** live-model card (version + rolling window + val metrics +
  old-rows-dropped), calibration scatter, PSI drift bar (with retrain threshold line), retraining
  history, and monitoring log — plus "Run monitoring check" and "Force retrain" buttons.

## CRM Tracker — Phase 5: Engagement Scoring & Upsell Engine

New `engagement_scorer.py`, an upsell engine in `interventions.py`, and engagement visuals in `dashboard.py`.

- **Composite 0–100 score** (`engagement_scorer.py`): session utilization 35% · app usage 25% ·
  email response 15% · retail spend 15% · consistency 10%. Verified scores span **0.0–100.0**
  (mean 70.6), joined with churn probability for the dual gauge → `data/member_engagement.parquet`.
- **Segments** (most-actionable label, with precedence): `upsell_candidate` (Basic + high),
  `under_engaged_payer` (Premium + low), `at_risk_silent`, `champion`, `engaged`. Tier-mismatch
  checks pass: 1,282 upsell_candidates **all Basic**, 15 under_engaged_payers **all Premium**
  ($75.6k/mo Basic upsell pipeline).
- **Upsell engine** (`interventions.py::run_upsell_engine`, `--upsell` flag): segment→campaign
  (UpsellEmail / WinValueEmail / EngageNudge / ReferralEmail), reusing the churn router's safety
  rails — dry-run default, deterministic 10% holdout, 7-day rate limit, global kill switch, full
  audit+queue. Verified dry-run: **1,987 dispatched**, 236 held out, 128 rate-limited, 0 failed.
- **Dashboard:** Member Detail now shows **dual gauges** (Churn Risk + Engagement) side by side;
  Studio Overview gains an **Engagement-vs-Churn quadrant map** (colored by segment) + segment
  summary, GM-scoped to their studio.
- Verified: all modules compile; engagement panel data shaped correctly.

## Security carry-overs — CLOSED

The two items flagged in the Phase 5 review are now fixed (verified):
- **`.gitignore`** re-excludes `data/` + `*.parquet`, so the encrypted identity blob can't be
  committed (esp. alongside the dev key). Confirmed `git check-ignore` now matches; 0 data files
  were ever tracked, so no untracking was needed. (Does NOT affect local files — restarts don't
  regenerate; only a fresh clone needs the one-time pipeline bootstrap.)
- **`secure_data.py` key/salt fail CLOSED in production:** with `HOTWORX_ENV=production` and no
  `HOTWORX_IDENTITY_ENCRYPTION_KEY`/`HOTWORX_IDENTITY_SALT` it raises rather than using the committed
  dev fallback. Local/demo (default `HOTWORX_ENV=dev`) still works with a loud warning — verified
  decrypt of 5,000 rows still succeeds.

## Admin "View as Studio" oversight lens

Added an Admin-only sidebar selector to view the exact GM-scoped experience for any single studio.

- **Not privilege escalation:** admins already see all data, so this is a *lens*, not new access.
  Implemented by threading `effective_studio` / `studio_scoped` (GM's own studio, or the admin's
  selection) through `get_scoped_connection` and every per-view filter (My Studio Today, Studio
  Overview + engagement map, Member Detail, Queue, A/B). "All studios" = the prior global admin view.
- **Read-only:** when an admin is in the lens (`oversight_readonly`), GM write-actions (Save Outcome,
  Mark Call as Completed) are disabled with a notice — no actions are taken as the GM.
- **Audited:** each (admin, studio) view is logged to `data/admin_oversight_log.parquet` (once per
  change, not per rerun).
- The cross-studio "Home Studio Risk Breakdown" hides while scoped to one studio; Revenue Impact and
  Model Health remain global org tools.
- Verified: compiles; scoping isolates correctly (admin→S03 sees 1 studio / 492 members / 372 scores
  of 3,740); GM behavior unchanged.

## GM Daily Welcome + Task List, and Win-Back Leaderboard with Bonus

Two GM-facing features.

### 1. Personalized daily digest with a named task list (`daily_digest.py`)
- Added a time-aware greeting ("Good morning, GM of S05! Here's your game plan for Sunday.") and a
  **🥇 win-back rank line** (rank, reactivation %, bonus pace) for motivation.
- Added a concrete **"Your Tasks Today"** section listing the actual people to follow up — top
  Critical/High members to call (with risk %), top win-back outreach targets (with MRR), and
  onboarding welcome check-ins — resolved from the (decrypted) identity table.

### 2. Win-Back Retention Leaderboard + year-end bonus (`winback_leaderboard.py` + dashboard)
- Ranks studios by **reactivation rate** (success at retaining originally-cancelled members).
- The base data had **no reactivation signal** (no re-joiner cohort — the deferred Phase-1 gap), so
  the module generates a clearly-marked **synthetic** reactivation cohort with per-studio success
  rates (8–22%) → `data/winback_reactivations.parquet`. Production would swap in observed
  cancelled→active transitions; the math is unchanged.
- **Year-end bonus pool** = 10% of recovered annual revenue, allocated proportionally to revenue
  each studio recovered (Σ awards = pool, verified). Champion: S05 (23.7%); pool $5,295.60.
- **Dashboard:** Admin "Win-Back Leaderboard" view (champion/pool KPIs, rate bar chart, ranked
  table with 🥇🥈🥉, bonus-allocation table) + a win-back **rank badge** on each GM's "My Studio Today"
  (also shown when an admin views a studio via the oversight lens).
- Honest labeling: rank = skill (rate); bonus = dollars recovered; reactivations = synthetic demo data.

## Generative AI Member Summaries (`ai_summary_engine.py` + Member Detail UI)

Hybrid GenAI feature: deterministic data layer + self-hosted Llama synthesis + tabbed GM UI.

- **Phase 1 — deterministic payload** (`build_member_payload`): exact metrics + recent coach chats,
  de-identified (no name/email/phone — injected at render time only), resolved via the encrypted
  identity table; DuckDB pushdown reads only the member's rows.
- **Phase 2 — LLM synthesis** (`synthesize_summary`): Ollama OpenAI-compatible endpoint
  (`llama3.1:8b-instruct-q8_0`, env-configurable), temp 0.2, strict JSON contract, prompt-injection
  guard on chat text, degradation chain **encrypted cache → LLM (validated) → rules fallback** (never
  raises). Anti-hallucination validator rejects multi-digit numbers absent from the payload —
  *fired live on first run*, caught "97.3%" which was a CORRECT percent form of 0.973, so the
  validator whitelists percent conversions of probability fields. Verified: live LLM output passes,
  cache hit, cache encrypted at rest (plain read fails), offline → rules fallback, cache gitignored.
- **Phase 3 — UI** (ui-ux-pro-max skill): Member Detail "Risk Explanation" replaced with tabs —
  **✨ AI Summary & Action Plan** (provenance badge LLM/Cached/Rules as color+dot+text, summary,
  numbered next steps, talking-point quotes, Regenerate) and **📊 Technical Breakdown** (the
  deterministic bullets). On-demand generation (never auto-calls the LLM on click; cached briefs
  render instantly); oversight lens is read-only (no generate/regenerate). Matches the current
  light theme. Verified via Streamlit AppTest: GM login renders cached badge + steps + quotes +
  Regenerate; admin oversight shows read-only notice and no buttons; no exceptions.
- **Phase 4 — offline test suite** (`test_ai_summary.py`, 11/11 passing, no Ollama needed; LLM
  mocked, cache redirected to temp): the three plan profiles (high-risk failed-billing+cancel-query,
  low-risk engaged, lapsed with no chats), anti-hallucination (invented numbers rejected; payload
  numbers + percent-forms of probabilities allowed), full degradation chain (good→llm, repeat→cache,
  hallucinated→rules, unparseable→rules, server-down→rules), prompt guards present, and real-payload
  PII check (no name/email/phone fields). Runs standalone or under pytest.

## Security — Auth audit log + lockout (SOC finding #1)

Closed the biggest detection blind spot: the login was previously unlogged and unthrottled.

- **`auth_audit.py`** (Streamlit-free, testable): every attempt (success/failure/lockout) appended
  to a **hash-chained JSONL** log `data/auth_audit.log` — each record carries the prior record's
  sha256, so deletion/edits are detectable via `verify_chain()` (tamper-evidence vs. T1070.004/T1565).
  Flat JSON for SIEM ingestion; password never logged.
- **Lockout** throttles brute force / spraying (T1110): ≥5 failures / 15 min (per username, and per
  source IP when known) → 15-min backoff, checked *before* password verification. Source-based
  lockout no-ops when source is `unknown` (proxy-less) to avoid an all-user DoS.
- **`dashboard.py`** login wired to log + lockout; best-effort source from `X-Forwarded-For` /
  `X-Real-Ip`. `auth_audit.py main()` is a SOC utility: chain integrity + last-hour failure summary
  by username/source (spray indicator).
- Verified: lockout fires at threshold, no collateral lock across users on `unknown` source, success
  resets the window, chain detects a tampered middle record (break at exact line); AppTest confirms
  real login logs `failure`→`success` with intact chain; log is gitignored.
- Production follow-ups (from the threat model): ship the log off-box, add MFA/SSO + session timeout,
  alert on kill-switch trips and `INTERVENTIONS_LIVE` flips.

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
