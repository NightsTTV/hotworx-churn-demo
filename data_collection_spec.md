# Data Collection Spec — HOTWORX Churn Control Center

A build checklist for wiring the system to **real** member data. Each signal lists its source
system, the event/endpoint to read, how to capture it (webhook vs. batch), expected latency, and
the **feature column it populates** in `fct_member_features_daily` (the daily per-member status table).

> **Two kinds of status.** Inactivity ("no session in 30 days") is an *objective computed fact*.
> Cancellation intent ("wants to cancel") is *assembled* from explicit "tells" + the model. The
> single biggest enabler under everything is **identity resolution** — every signal lives in a
> different system and must be stitched to one person (`hashed_member_id`).

Legend — **Capture**: `Webhook` (real-time push) · `Stream` (event pipeline) · `Batch` (nightly ETL pull).
⚠️ = needs **new instrumentation** (data exists but isn't captured as a signal yet).

---

## A. Session / activity  → inactivity & attendance

| Signal | Source system | Event / endpoint | Capture | Latency | Feature column(s) | Staging |
|---|---|---|---|---|---|---|
| Session booked | Burn Off App / TrainingTRAX | `booking.created` / bookings table | Webhook + Batch | minutes / daily | `sessions_booked_7d/30d` | `stg_sessions` |
| Session attended (check-in) | Sauna door/24-7 access · app check-in · instructor | door access log · `checkin` event · attendance table | Webhook + Batch | minutes / daily | `sessions_attended_7d/30d`, `days_since_last_session`, `attendance_rate_7d/30d` | `stg_sessions` |
| Sauna temperature | Equipment / session record | session detail | Batch | daily | `avg_sauna_temp_30d` | `stg_sessions` |

**Inactivity** is simply `today − max(attended_session_date)`. Requires every entry point (door + app + instructor) to log reliably.

## B. Billing / payments  → payment failure, price, tenure, churn label

| Signal | Source system | Event / endpoint | Capture | Latency | Feature column(s) | Staging |
|---|---|---|---|---|---|---|
| Recurring payment failed/declined | Square | `invoice.payment_failed`, dunning webhooks | **Webhook** | real-time | `last_recurring_payment_failed`, `failed_payments_count_30d` | `stg_transactions` |
| Recurring payment success | Square | `payment.succeeded` | Webhook + Batch | real-time / daily | (resolves failure flags) | `stg_transactions` |
| Membership tier & price | SailPOS | membership record | Batch | daily | `monthly_price`, `membership_tier` | `stg_memberships` |
| Join date / tenure | SailPOS | membership start | Batch | daily | `tenure_days` | `stg_memberships` |
| **Cancellation (the churn LABEL)** | SailPOS + Square | `subscription.canceled`, `status=Cancelled`, `cancel_date` | Webhook + Batch | real-time / daily | `is_churned_14d` (training label), lifecycle `cancelled` stage | `stg_memberships`, `stg_ground_truth` |

> The cancellation *fact* feeds the **label** only — never as a live model feature (no leakage).

## C. App engagement  → digital activity

| Signal | Source system | Event / endpoint | Capture | Latency | Feature column(s) | Staging |
|---|---|---|---|---|---|---|
| App opens / logins | Burn Off App | `session_start` analytics event | Stream + Batch | daily | `app_logins_7d/30d` | `stg_app_events` |
| Metric / after-burn views | Burn Off App | screen-view events | Batch | daily | `metric_views_30d` | `stg_app_events` |

## D. Email engagement (HW Campaign)

| Signal | Source system | Event / endpoint | Capture | Latency | Feature column(s) | Staging |
|---|---|---|---|---|---|---|
| Emails sent | HW Campaign | campaign send log | Batch | daily | `emails_sent_30d` | `stg_email_events` |
| Opens | HW Campaign | open-tracking | Batch | daily | `emails_opened_30d`, `email_open_rate_30d` | `stg_email_events` |
| Clicks | HW Campaign | click-tracking | Batch | daily | `emails_clicked_30d` | `stg_email_events` |
| ⚠️ Unsubscribe | HW Campaign | `unsubscribe` event | Webhook + Batch | daily | *new:* `email_unsubscribed` (intent signal) | `stg_email_events` |

## E. Cancellation intent  → assembled "wants to cancel" signals

| Signal | Source system | Event / endpoint | Capture | Latency | Feature column(s) | Staging |
|---|---|---|---|---|---|---|
| AI-coach "how do I cancel/freeze/pause" | Burn Off App / TrainingTRAX | chat transcript → **intent classifier** | Batch (NLP) | daily | `has_cancellation_query_30d`, `coach_chat_count_30d` | `stg_ai_coach_chats` |
| ⚠️ Front-desk cancel/freeze inquiry | SailPOS CRM notes | **structured tag** (button, not free-text) | Batch | daily | `has_cancellation_query_30d` | `stg_ai_coach_chats` (or new `stg_staff_notes`) |
| ⚠️ Freeze / cancel form started | Member portal | `form.submitted` (`/cancel`, `/freeze`) | **Webhook** | real-time | *new:* `cancel_form_started` | new `stg_portal_events` |
| ⚠️ Cancel / billing page visited | Member portal | pageview (`/cancel`, `/billing`) | Stream + Batch | daily | *new:* `visited_cancel_page_30d` | new `stg_portal_events` |
| ⚠️ Cancellation / billing support ticket | Mojo Helpdesk | `ticket.created` (tagged) | Webhook + Batch | daily | *new:* `support_cancel_ticket_30d` | new `stg_support_tickets` |

> "Wants to cancel" is **not** a single field — it's the **churn-risk score** elevated by these
> explicit flags. The flags are model features + the explanation chips shown in Member Detail.

## F. Identity & demographics  → resolution, outreach, base features

| Signal | Source system | Event / endpoint | Capture | Latency | Use | Staging |
|---|---|---|---|---|---|---|
| Name / email / phone | SailPOS + App + HW Campaign | member profile | Batch | daily | **identity resolution** → `hashed_member_id`; outreach | `int_member_identity` (encrypted) |
| Gender, DOB/age | SailPOS profile | member profile | Batch | daily | `gender`, `age` | `stg_members` |
| Retail purchases | SailPOS / Square | line items (non-membership) | Webhook + Batch | daily | `retail_spend_30d` | `stg_transactions` |

---

## Collection architecture

```
 Real-time (Webhook/Stream)        Nightly Batch (ETL)
 ──────────────────────────        ───────────────────
 Square billing webhooks           SailPOS membership/status/profile
 App check-ins, logins, chats      HW Campaign email engagement
 Portal cancel/billing events      Mojo Helpdesk tickets
 Unsubscribe events                App session/booking history
            │                              │
            └───────────────┬──────────────┘
                            ▼
                IDENTITY RESOLUTION  (one person across systems → hashed_member_id)
                            ▼
            DAILY STATUS SNAPSHOT  (fct_member_features_daily: 1 row / member / day)
                            ▼
            Churn model → risk score · lifecycle stage · engagement score
```

- **Fast intent signals** (billing failure, cancel-page visit, cancel chat) → webhook/stream so a
  member is flagged within minutes.
- **Slower signals** (attendance, email, membership) → nightly batch.
- Both converge into the same **daily per-member status row** — the structure already built; only the
  source changes from synthetic to real.

---

## Instrumentation gaps to close (the ⚠️ rows)

1. **AI-coach chat intent logging** — store transcripts + run a cancel/freeze intent classifier (upgrade from keyword matching to a small NLP model).
2. **Portal analytics** — emit events for cancel/billing/freeze page views and form starts.
3. **Square billing webhooks** — subscribe payment-failed / dunning / subscription-canceled to the pipeline.
4. **Structured front-desk tags** — replace free-text notes with a "cancellation inquiry / freeze request" action so it's machine-readable.
5. **Reliable check-in capture** at every entry point (door + app + instructor) — the foundation of the inactivity signal.

## Data-quality gates (run on every real feed)
- Freshness (each source updated within SLA) · volume anomaly alerts · null/range checks (reuse `run_pipeline.py` Test A/B) · PII-leakage check (Test C) · identity match-rate monitoring.

## Privacy & consent
- Identity table stays encrypted at rest (`secure_data.py`, fail-closed in prod).
- Honor `intervention_opt_out` and right-to-delete across feature store, scores, audit, and identity.
- Cancellation-intent signals are sensitive — restrict access (GM sees own studio; admin oversight is logged).
