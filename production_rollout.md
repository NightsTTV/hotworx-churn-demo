# Production Rollout — From Synthetic Demo to Real Client Conclusions

How to take this system live on real HOTWORX data and produce **trustworthy** conclusions.
Companion to `data_collection_spec.md` (which maps each signal → source → feature column).
This doc covers *what becomes real when*, and *what makes each conclusion valid*.

> **Core principle.** Conclusions fall into three tiers by difficulty. Some come from a historical
> data dump next week; others fundamentally require running the program **forward in time** with a
> holdout. Conflating these is how analytics projects overpromise.

---

## Tier 1 — Derivable now (ingest + compute)

Facts or formulas — no experiment needed, just clean data + identity resolution.

| Conclusion | Real source | How it's derived | "Done" when |
|---|---|---|---|
| Cancellations / lifecycle stage | SailPOS + Square | Recorded fact: `status`, `cancel_date`, billing state → stage rules (`lifecycle_stages.py`) | Stages match the membership system 1:1 |
| Engagement score & segments | App, HW Campaign, Square | Composite formula on real features (`engagement_scorer.py`) | Scores populate; **weights validated** vs. observed retention |
| Cohort retention curve | Membership join/cancel dates | Kaplan-Meier on real tenancies (`revenue_metrics.py`) | Curve reproduces known retention rates |

**These are your quick wins** — real numbers within weeks of read access.

## Tier 2 — Needs enough history (train on the rolling window)

| Conclusion | What it requires | "Done" when |
|---|---|---|
| Churn risk scores | (a) signed-off **churn definition**, (b) **18–24 mo** of real cancellations as labels (rolling-window principle, `train_model.py`), (c) real behavioral features | Backtest on held-out recent months meets AUC/PR-AUC bar |
| Win-back reactivations / leaderboard / bonus | Track **cancelled→re-joined** transitions (needs identity link to prior cancelled identity) | Reactivations sourced from real transitions; synthetic generator retired |

Hard dependency: **identity resolution** (`identity_resolver.py` + `playbook_identity_resolution.md`).

## Tier 3 — Cannot be dumped; must run forward (experiment + time)

The honest, highest-value tier.

| Conclusion | Why a dump can't produce it | How to derive it for real | "Done" when |
|---|---|---|---|
| Saved revenue / intervention lift | "Saved" is **causal** — can't observe the counterfactual | **Holdout** (built): withhold 10%, measure treatment-vs-holdout churn × MRR forward 30/60/90d. Replace assumed 25%/8% factors with measured lift | A statistically meaningful lift estimate exists |
| Intervention effectiveness (closed loop) | Outcomes exist only after real sends | Run engines live → `outcome_tracker.py` watches real forward windows | Every Sent intervention has a forward outcome |
| Model drift / calibration | Needs predictions vs. realized outcomes over time | Accrues once deployed; `model_monitor.py` computes PSI + calibration | Monitor has ≥2 cycles of live data |

**Discipline that makes Tier 3 trustworthy: keep the holdout from day one, and never quote a causal
number you haven't measured against it.** (This is why the demo's saved-revenue / A-B / win-back
figures are labeled estimates.)

---

## Non-negotiables before any conclusion is valid

1. **Identity resolution** — the #1 blocker. Build + QA the cross-system match (email + phone + fuzzy
   name → stable `hashed_member_id`) and monitor match rate before trusting any joined metric.
2. **Churn definition sign-off** — a documented, agreed rule (cancelled? frozen? N-day failed billing?).
   Every downstream number depends on it.
3. **Data-quality gates** — `run_pipeline.py` Tests A/B/C against real feeds + freshness/volume alerts.
4. **Holdout + measurement plan** — instrumented *before* launch, not after.
5. **PII & consent** — encryption at rest (`secure_data.py`, fail-closed in prod); honor
   `intervention_opt_out` + right-to-delete across feature store, scores, audit, identity.

---

## Phased rollout sequence

1. **Read-only connect** one studio's SailPOS + app + HW Campaign + Square via `data_adapters.py`
   (pipeline SQL is warehouse-portable: DuckDB → Snowflake/BigQuery).
2. **Resolve identity** for that studio; validate match rates manually.
3. **Backfill Tier 1** (lifecycle, engagement, retention) → show real numbers, build trust.
4. **Train Tier 2** churn model on the rolling window once ≥18 mo of real cancellations exist;
   backtest before trusting scores. Stand up win-back tracking.
5. **Launch interventions in dry-run**, confirm targeting looks sane to GMs, then go live **with the
   holdout** (`INTERVENTIONS_LIVE=true`, real adapter keys from a secrets manager).
6. **Let Tier 3 accrue** — after 30/60/90d you have *measured* saved revenue, win-back lift, and
   drift. Swap every assumed factor for its measured value.
7. **Roll out studio-by-studio**, comparing each new studio's early numbers to the proven ones.

---

## One-line summary

**Ingest gets you Tier 1, history gets you Tier 2, and only running the program with a holdout gets
you Tier 3** — and Tier 3 is where the dollar claims (and the GM bonus) become *defensible* rather
than *estimated*.

## Related docs & hooks
- `data_collection_spec.md` — per-signal source → feature-column build checklist.
- `playbook_identity_resolution.md` / `identity_resolver.py` — cross-system identity matching.
- `data_adapters.py` — swap synthetic parquet reads for real source connections (6 stubs).
- `SECURITY.md` / `handoff_runbook.md` — threat model + ops.
- `CHANGELOG.md` — full build history.
