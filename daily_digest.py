"""
Multi-Channel Daily Digest Engine
===================================
Sends automated daily GM summaries through the franchise's preferred communication
channel (Slack, Teams, Email, or generic Webhook for GroupMe/Workforce.com).

HOTWORX Communication Landscape:
  - GM-to-staff / GM-to-regional: Franchisee-specific (Slack, Teams, GroupMe, Workforce.com)
  - GM-to-corporate: Corporate email, phone lines, franchise portals
  - GM-to-member: HOTWORX Burn Off App + TrainingTRAX platform

Each franchise configures their preferred channel via GM_DIGEST_CHANNEL env var.
"""

import os
import sys
import json
import datetime
from abc import ABC, abstractmethod
import pandas as pd

DATA_DIR = "./data"
LIFECYCLE_PATH = os.path.join(DATA_DIR, "member_lifecycle.parquet")
SCORES_PATH = os.path.join(DATA_DIR, "churn_scores_daily.parquet")
FEATURES_PATH = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
QUEUE_PATH = os.path.join(DATA_DIR, "intervention_queue.parquet")
OUTCOMES_PATH = os.path.join(DATA_DIR, "intervention_outcomes.parquet")
IDENTITY_PATH = os.path.join(DATA_DIR, "int_member_identity.parquet")


# ==============================================================================
# DIGEST ADAPTER PATTERN
# ==============================================================================
class DigestAdapter(ABC):
    """Base class for digest delivery channels."""

    @abstractmethod
    def send_digest(self, studio_id: str, gm_name: str, digest_html: str, digest_text: str) -> bool:
        """Send formatted digest to the GM's preferred channel.

        Args:
            studio_id: Studio identifier (e.g. "S01")
            gm_name: GM's display name
            digest_html: Rich HTML formatted digest (for email/Teams)
            digest_text: Plain text fallback (for Slack/SMS)

        Returns:
            True if delivery succeeded
        """
        pass


class SlackDigestAdapter(DigestAdapter):
    """Deliver digest via Slack webhook to a studio's channel."""

    def __init__(self, live_mode: bool = False):
        self.live_mode = live_mode
        self.webhook_url = os.getenv("SLACK_DIGEST_WEBHOOK_URL")

    def send_digest(self, studio_id: str, gm_name: str, digest_html: str, digest_text: str) -> bool:
        if self.live_mode:
            if not self.webhook_url:
                raise ValueError("SlackDigestAdapter CONFIG ERROR: SLACK_DIGEST_WEBHOOK_URL is missing.")
            import requests
            payload = {
                "text": f"*🔥 HOTWORX Daily Digest — {studio_id}*\n\n{digest_text}",
                "username": "HOTWORX Churn Control",
                "icon_emoji": ":fire:"
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            print(f"[Slack LIVE] Digest sent to {studio_id} channel")
        else:
            print(f"[Slack DRY-RUN] Would send digest to {studio_id} channel | Length: {len(digest_text)} chars")
        return True


class TeamsDigestAdapter(DigestAdapter):
    """Deliver digest via Microsoft Teams webhook."""

    def __init__(self, live_mode: bool = False):
        self.live_mode = live_mode
        self.webhook_url = os.getenv("TEAMS_DIGEST_WEBHOOK_URL")

    def send_digest(self, studio_id: str, gm_name: str, digest_html: str, digest_text: str) -> bool:
        if self.live_mode:
            if not self.webhook_url:
                raise ValueError("TeamsDigestAdapter CONFIG ERROR: TEAMS_DIGEST_WEBHOOK_URL is missing.")
            import requests
            # Teams Adaptive Card format
            payload = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "summary": f"HOTWORX Daily Digest — {studio_id}",
                "themeColor": "FF4500",
                "title": f"🔥 HOTWORX Daily Digest — {studio_id}",
                "sections": [{
                    "text": digest_html,
                    "markdown": True
                }]
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            print(f"[Teams LIVE] Digest sent to {studio_id} channel")
        else:
            print(f"[Teams DRY-RUN] Would send digest to {studio_id} channel | Length: {len(digest_text)} chars")
        return True


class EmailDigestAdapter(DigestAdapter):
    """Deliver digest via email (SMTP or HW Campaign API). Fallback for franchises without Slack/Teams."""

    def __init__(self, live_mode: bool = False):
        self.live_mode = live_mode

    def send_digest(self, studio_id: str, gm_name: str, digest_html: str, digest_text: str) -> bool:
        if self.live_mode:
            # In production, use SMTP or HW Campaign API
            smtp_host = os.getenv("SMTP_HOST")
            gm_email = os.getenv(f"GM_EMAIL_{studio_id}", os.getenv("GM_FALLBACK_EMAIL"))
            if not smtp_host or not gm_email:
                raise ValueError(f"EmailDigestAdapter CONFIG ERROR: SMTP_HOST or GM_EMAIL_{studio_id} is missing.")

            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"🔥 HOTWORX Daily Digest — {studio_id} — {datetime.date.today()}"
            msg["From"] = os.getenv("SMTP_FROM", "noreply@hotworx-churn.com")
            msg["To"] = gm_email

            msg.attach(MIMEText(digest_text, "plain"))
            msg.attach(MIMEText(digest_html, "html"))

            with smtplib.SMTP(smtp_host, int(os.getenv("SMTP_PORT", "587"))) as server:
                server.starttls()
                server.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASS", ""))
                server.send_message(msg)

            print(f"[Email LIVE] Digest sent to {gm_email} for {studio_id}")
        else:
            print(f"[Email DRY-RUN] Would send digest to GM of {studio_id} | Subject: HOTWORX Daily Digest")
        return True


class WebhookDigestAdapter(DigestAdapter):
    """Generic webhook adapter for GroupMe, Workforce.com, or any custom integration."""

    def __init__(self, live_mode: bool = False):
        self.live_mode = live_mode
        self.webhook_url = os.getenv("GM_DIGEST_WEBHOOK_URL")

    def send_digest(self, studio_id: str, gm_name: str, digest_html: str, digest_text: str) -> bool:
        if self.live_mode:
            if not self.webhook_url:
                raise ValueError("WebhookDigestAdapter CONFIG ERROR: GM_DIGEST_WEBHOOK_URL is missing.")
            import requests
            payload = {
                "studio_id": studio_id,
                "gm_name": gm_name,
                "timestamp": datetime.datetime.now().isoformat(),
                "digest_text": digest_text,
                "digest_html": digest_html,
                "source": "hotworx_churn_control"
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            print(f"[Webhook LIVE] Digest sent to {studio_id} via custom webhook")
        else:
            print(f"[Webhook DRY-RUN] Would POST digest to {studio_id} via custom webhook | Length: {len(digest_text)} chars")
        return True


# ==============================================================================
# DIGEST CONTENT BUILDER
# ==============================================================================
def _build_task_section(studio_id: str) -> tuple[list, list]:
    """Build the concrete, NAMED task list for a GM's day (the actual people to follow up)."""
    text, html = [], []
    try:
        import secure_data
        if not (os.path.exists(SCORES_PATH) and os.path.exists(FEATURES_PATH) and os.path.exists(IDENTITY_PATH)):
            return text, html
        scores = pd.read_parquet(SCORES_PATH)
        feats = pd.read_parquet(FEATURES_PATH)
        latest = scores["score_date"].max()
        s = scores[scores["score_date"] == latest].merge(
            feats[feats["date_day"] == latest][["hashed_member_id", "home_studio_id"]],
            on="hashed_member_id",
        )
        s = s[s["home_studio_id"] == studio_id]
        ident = secure_data.read_encrypted_parquet(IDENTITY_PATH)[["hashed_member_id", "name"]]
        s = s.merge(ident, on="hashed_member_id", how="left")

        tasks_text, tasks_html = [], []
        # 1. High-severity follow-up calls (Critical + High), worst first.
        hi = s[s["risk_tier"].isin(["Critical", "High"])].sort_values("churn_probability", ascending=False).head(6)
        for _, r in hi.iterrows():
            tasks_text.append(f"  📞 Call {r['name']} — {r['risk_tier']} risk ({r['churn_probability']:.0%})")
            tasks_html.append(f"<li>📞 <strong>Call {r['name']}</strong> — {r['risk_tier']} risk ({r['churn_probability']:.0%})</li>")

        # 2. Win-back outreach + onboarding welcomes (from lifecycle).
        if os.path.exists(LIFECYCLE_PATH):
            lc = pd.read_parquet(LIFECYCLE_PATH)
            lc_s = lc[lc["home_studio_id"] == studio_id]
            wb = (lc_s[lc_s["stage"] == "win_back_eligible"].merge(ident, on="hashed_member_id", how="left")
                  .sort_values("monthly_price", ascending=False).head(4))
            for _, r in wb.iterrows():
                tasks_text.append(f"  💚 Win-back outreach: {r['name']} (${r['monthly_price']:.0f}/mo)")
                tasks_html.append(f"<li>💚 <strong>Win-back:</strong> {r['name']} (${r['monthly_price']:.0f}/mo)</li>")
            ob = lc_s[lc_s["stage"] == "onboarding"].merge(ident, on="hashed_member_id", how="left").head(3)
            for _, r in ob.iterrows():
                tasks_text.append(f"  👋 Welcome check-in: {r['name']}")
                tasks_html.append(f"<li>👋 <strong>Welcome check-in:</strong> {r['name']}</li>")

        if tasks_text:
            text.append("\n✅ YOUR TASKS TODAY:")
            text.extend(tasks_text)
            html.append("<h3>✅ Your Tasks Today</h3><ul>" + "".join(tasks_html) + "</ul>")
        else:
            text.append("\n✅ YOUR TASKS TODAY: All clear — no high-priority follow-ups. 🎉")
            html.append("<h3>✅ Your Tasks Today</h3><p>All clear — no high-priority follow-ups. 🎉</p>")
    except Exception as e:
        text.append(f"\n(Task list unavailable: {e})")
    return text, html


def build_digest_content(studio_id: str) -> tuple[str, str]:
    """Build the digest content for a specific studio.

    Returns:
        Tuple of (html_content, text_content)
    """
    today = datetime.date.today()
    sections_text = []
    sections_html = []

    # ---- Header ----
    gm_label = f"GM of {studio_id}"
    greeting = "Good morning" if datetime.datetime.now().hour < 12 else "Hello"
    sections_text.append(f"HOTWORX DAILY DIGEST — {studio_id} — {today}")
    sections_text.append("=" * 50)
    sections_text.append(f"{greeting}, {gm_label}! Here's your game plan for {today:%A}.")
    sections_html.append(f"<h2>🔥 HOTWORX Daily Digest — {studio_id}</h2>")
    sections_html.append(f"<p style='color:#8A8F98;'>{today}</p>")
    sections_html.append(f"<p><strong>{greeting}, {gm_label}!</strong> Here's your game plan for {today:%A}.</p>")

    # ---- Win-back rank (motivation / bonus race) ----
    try:
        import winback_leaderboard as wbl
        rk = wbl.get_studio_rank(studio_id)
        if rk:
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rk["rank"], "🏆")
            sections_text.append(
                f"{medal} Win-back rank: #{rk['rank']} of {rk['of']} "
                f"({rk['reactivation_rate']:.0%} reactivation · ${rk['bonus_award']:,.0f} bonus pace)")
            sections_html.append(
                f"<p>{medal} <strong>Win-back rank: #{rk['rank']} of {rk['of']}</strong> "
                f"({rk['reactivation_rate']:.0%} reactivation · ${rk['bonus_award']:,.0f} bonus pace)</p>")
    except Exception:
        pass

    # ---- Load data ----
    has_lifecycle = os.path.exists(LIFECYCLE_PATH)
    has_scores = os.path.exists(SCORES_PATH)
    has_queue = os.path.exists(QUEUE_PATH)
    has_outcomes = os.path.exists(OUTCOMES_PATH)

    # ---- Critical Actions ----
    critical_calls = 0
    payment_failures = 0
    inactive_14d = 0

    if has_scores and os.path.exists(FEATURES_PATH):
        scores_df = pd.read_parquet(SCORES_PATH)
        features_df = pd.read_parquet(FEATURES_PATH)
        latest_date = scores_df["score_date"].max()

        latest_scores = scores_df[scores_df["score_date"] == latest_date]
        latest_features = features_df[features_df["date_day"] == latest_date]

        studio_scores = latest_scores.merge(
            latest_features[["hashed_member_id", "home_studio_id", "last_recurring_payment_failed", "days_since_last_session"]],
            on="hashed_member_id"
        )
        studio_data = studio_scores[studio_scores["home_studio_id"] == studio_id]

        critical_calls = len(studio_data[studio_data["risk_tier"] == "Critical"])
        payment_failures = len(studio_data[studio_data["last_recurring_payment_failed"] == True])
        inactive_14d = len(studio_data[studio_data["days_since_last_session"] > 14])

    sections_text.append(f"\n📌 ACTION ITEMS:")
    sections_text.append(f"  🔴 {critical_calls} critical calls needed")
    sections_text.append(f"  💳 {payment_failures} payment failures to resolve")
    sections_text.append(f"  💤 {inactive_14d} members inactive 14+ days")

    sections_html.append("<h3>📌 Action Items</h3>")
    sections_html.append(f"<p>🔴 <strong>{critical_calls}</strong> critical calls needed</p>")
    sections_html.append(f"<p>💳 <strong>{payment_failures}</strong> payment failures to resolve</p>")
    sections_html.append(f"<p>💤 <strong>{inactive_14d}</strong> members inactive 14+ days</p>")

    # ---- Named task list (the actual people to follow up today) ----
    _task_text, _task_html = _build_task_section(studio_id)
    sections_text.extend(_task_text)
    sections_html.extend(_task_html)

    # ---- Lifecycle Summary ----
    if has_lifecycle:
        lifecycle_df = pd.read_parquet(LIFECYCLE_PATH)
        studio_lc = lifecycle_df[lifecycle_df["home_studio_id"] == studio_id]

        if not studio_lc.empty:
            stage_counts = studio_lc["stage"].value_counts()
            wb_count = stage_counts.get("win_back_eligible", 0)
            at_risk_count = stage_counts.get("at_risk", 0)
            onboarding_count = stage_counts.get("onboarding", 0)

            sections_text.append(f"\n📊 MEMBER LIFECYCLE:")
            sections_text.append(f"  At-risk: {at_risk_count} | Win-back eligible: {wb_count} | Onboarding: {onboarding_count}")

            sections_html.append("<h3>📊 Member Lifecycle</h3>")
            sections_html.append(
                f"<p>At-risk: <strong>{at_risk_count}</strong> · "
                f"Win-back eligible: <strong>{wb_count}</strong> · "
                f"Onboarding: <strong>{onboarding_count}</strong></p>"
            )

            if wb_count > 0:
                wb_revenue = studio_lc[studio_lc["stage"] == "win_back_eligible"]["monthly_price"].sum()
                sections_text.append(f"  💰 Win-back revenue opportunity: ${wb_revenue:,.0f}/mo")
                sections_html.append(f"<p>💰 Win-back revenue opportunity: <strong>${wb_revenue:,.0f}/mo</strong></p>")

    # ---- Yesterday's Outcomes ----
    if has_outcomes:
        outcomes_df = pd.read_parquet(OUTCOMES_PATH)
        if not outcomes_df.empty:
            # Count recent positive outcomes
            positive = outcomes_df["outcome_30d"].isin(["re_engaged", "payment_resolved", "still_active"]).sum()
            total = len(outcomes_df)
            rate = (positive / total * 100) if total > 0 else 0

            sections_text.append(f"\n📈 INTERVENTION EFFECTIVENESS:")
            sections_text.append(f"  {positive}/{total} interventions had positive outcomes ({rate:.0f}%)")

            sections_html.append("<h3>📈 Intervention Effectiveness</h3>")
            sections_html.append(f"<p>{positive}/{total} interventions had positive outcomes (<strong>{rate:.0f}%</strong>)</p>")

    # ---- Footer with dashboard link ----
    dashboard_url = os.getenv("DASHBOARD_URL", "http://localhost:8501")
    sections_text.append(f"\n🔗 View full dashboard: {dashboard_url}")
    sections_html.append(f"<br><p><a href='{dashboard_url}' style='color:#5F57FF;'>🔗 Open Dashboard →</a></p>")

    return "\n".join(sections_html), "\n".join(sections_text)


# ==============================================================================
# DIGEST DISPATCHER
# ==============================================================================
def get_adapter(live_mode: bool = False) -> DigestAdapter:
    """Get the configured digest adapter based on GM_DIGEST_CHANNEL env var."""
    channel = os.getenv("GM_DIGEST_CHANNEL", "email").lower()

    adapters = {
        "slack": SlackDigestAdapter,
        "teams": TeamsDigestAdapter,
        "email": EmailDigestAdapter,
        "webhook": WebhookDigestAdapter,
    }

    adapter_class = adapters.get(channel, EmailDigestAdapter)
    return adapter_class(live_mode=live_mode)


def run_daily_digest():
    """Main entry point: build and send digest to all studios."""
    print("=" * 60)
    print("HOTWORX DAILY DIGEST ENGINE")
    print("=" * 60)

    live_mode = os.getenv("DIGEST_LIVE", "false").lower() == "true"
    adapter = get_adapter(live_mode=live_mode)
    channel = os.getenv("GM_DIGEST_CHANNEL", "email").lower()

    print(f"Channel: {channel} | Live: {live_mode}")
    print(f"Adapter: {adapter.__class__.__name__}")

    # Determine studios to send digests to
    if os.path.exists(LIFECYCLE_PATH):
        lifecycle_df = pd.read_parquet(LIFECYCLE_PATH)
        studios = sorted(lifecycle_df["home_studio_id"].dropna().unique())
    elif os.path.exists(SCORES_PATH):
        scores_df = pd.read_parquet(SCORES_PATH)
        features_df = pd.read_parquet(FEATURES_PATH)
        latest_date = scores_df["score_date"].max()
        latest = features_df[features_df["date_day"] == latest_date]
        studios = sorted(latest["home_studio_id"].dropna().unique())
    else:
        print("No data found to build digests from.")
        return

    print(f"\nSending digests to {len(studios)} studios...")
    print("-" * 60)

    success_count = 0
    fail_count = 0

    for studio_id in studios:
        gm_name = f"GM_{studio_id}"  # In production, resolve from user database

        try:
            html_content, text_content = build_digest_content(studio_id)
            adapter.send_digest(studio_id, gm_name, html_content, text_content)
            success_count += 1
        except Exception as e:
            print(f"FAILED to send digest for {studio_id}: {e}")
            fail_count += 1

    print("-" * 60)
    print(f"Digests sent: {success_count} | Failed: {fail_count}")
    print("=" * 60)
    print("DAILY DIGEST COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    run_daily_digest()
