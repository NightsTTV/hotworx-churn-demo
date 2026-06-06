import os
import sys
import uuid
import hashlib
import datetime
import time
import pandas as pd
import duckdb
import requests

DATA_DIR = "./data"
AUDIT_LOG_PATH = os.path.join(DATA_DIR, "intervention_audit_log.parquet")
QUEUE_PATH = os.path.join(DATA_DIR, "intervention_queue.parquet")
IDENTITY_PATH = os.path.join(DATA_DIR, "int_member_identity.parquet")

GLOBAL_LIMIT_HOURLY = 50

# ==============================================================================
# HTTP RESILIENCE LAYER (RETRY & BACKOFF)
# ==============================================================================
def execute_request_with_retry(method: str, url: str, max_retries=3, backoff_factor=2.0, **kwargs):
    """Execute HTTP requests with exponential backoff retry logic. Fails loudly on success drop."""
    retries = 0
    delay = 1.0
    while retries < max_retries:
        try:
            response = requests.request(method, url, timeout=10, **kwargs)
            # Raise exception for 4xx/5xx responses to fail loudly
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            retries += 1
            if retries >= max_retries:
                raise ConnectionError(f"HTTP Outbound Connection Failed to {url} after {max_retries} retries: {str(e)}")
            print(f"[Outbound Retry Warning] Attempt {retries} failed for {url}. Retrying in {delay:.1f}s...")
            time.sleep(delay)
            delay *= backoff_factor

# ==============================================================================
# DETECTED/LIVE INTERVENTION ADAPTERS
# ==============================================================================
class HWCampaignAdapter:
    """Live adapter for HW Campaign email service. Fail loudly in Live Mode."""
    def __init__(self, live_mode=False):
        self.live_mode = live_mode
        self.api_key = os.getenv("HW_CAMPAIGN_API_KEY")
        self.endpoint = os.getenv("HW_CAMPAIGN_API_URL", "https://api.hwcampaign.com/v1/emails")

    def send_email(self, email: str, subject: str, body: str):
        if self.live_mode:
            if not self.api_key:
                raise ValueError("HWCampaignAdapter CONFIG ERROR: HW_CAMPAIGN_API_KEY is missing from environment. Cannot send in live mode.")
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "recipient": email,
                "subject": subject,
                "body": body
            }
            print(f"[HW Campaign LIVE] Dispatching re-engagement email to {email}...")
            execute_request_with_retry("POST", self.endpoint, json=payload, headers=headers)
        else:
            print(f"[HW Campaign DRY-RUN] Would send email to {email} | Subject: {subject}")
        return True

class TwilioAdapter:
    """Live adapter for Twilio SMS service. Fail loudly in Live Mode."""
    def __init__(self, live_mode=False):
        self.live_mode = live_mode
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = os.getenv("TWILIO_FROM_NUMBER", "+15550001111")

    def send_sms(self, phone: str, message: str):
        if self.live_mode:
            if not self.account_sid or not self.auth_token:
                raise ValueError("TwilioAdapter CONFIG ERROR: TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN is missing. Cannot send in live mode.")
            
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
            data = {
                "From": self.from_number,
                "To": phone,
                "Body": message
            }
            print(f"[Twilio LIVE] Dispatching SMS alert to {phone}...")
            execute_request_with_retry("POST", url, auth=(self.account_sid, self.auth_token), data=data)
        else:
            print(f"[Twilio DRY-RUN] Would send SMS to {phone} | Msg: {message}")
        return True

class PushNotificationAdapter:
    """Live adapter for Mobile App Push notification via FCM. Fail loudly in Live Mode."""
    def __init__(self, live_mode=False):
        self.live_mode = live_mode
        self.server_key = os.getenv("PUSH_SERVER_KEY")
        self.project_id = os.getenv("FCM_PROJECT_ID", "hotworx-churn-demo")

    def send_push(self, member_id: str, title: str, body: str):
        if self.live_mode:
            if not self.server_key:
                raise ValueError("PushNotificationAdapter CONFIG ERROR: PUSH_SERVER_KEY is missing. Cannot send in live mode.")
            
            url = f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send"
            headers = {
                "Authorization": f"Bearer {self.server_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "message": {
                    "token": f"device_token_placeholder_{member_id}",
                    "notification": {
                        "title": title,
                        "body": body
                    }
                }
            }
            print(f"[Push LIVE] Dispatching push notification to {member_id}...")
            execute_request_with_retry("POST", url, json=payload, headers=headers)
        else:
            print(f"[Push DRY-RUN] Would send push to {member_id} | Title: {title}")
        return True

# ==============================================================================
# AUDIT LOG AND QUEUE MANAGER
# ==============================================================================
def initialize_parquet_files():
    """Create empty parquet files if they do not exist with appropriate schemas."""
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if not os.path.exists(AUDIT_LOG_PATH):
        audit_df = pd.DataFrame(columns=[
            "audit_id", "member_id", "hashed_member_id", "sent_at", 
            "action_type", "status", "why_score", "message_body", "error_message"
        ])
        audit_df.to_parquet(AUDIT_LOG_PATH, index=False)
        print("Initialized empty intervention audit log parquet file.")
        
    if not os.path.exists(QUEUE_PATH):
        queue_df = pd.DataFrame(columns=[
            "action_id", "member_id", "hashed_member_id", "home_studio_id", 
            "score_date", "risk_score", "risk_tier", "action_type", 
            "action_details", "status", "created_at", "processed_at"
        ])
        queue_df.to_parquet(QUEUE_PATH, index=False)
        print("Initialized empty intervention queue parquet file.")

def load_audit_log() -> pd.DataFrame:
    initialize_parquet_files()
    return pd.read_parquet(AUDIT_LOG_PATH)

def load_queue() -> pd.DataFrame:
    initialize_parquet_files()
    return pd.read_parquet(QUEUE_PATH)

def save_audit_log(df: pd.DataFrame):
    df.to_parquet(AUDIT_LOG_PATH, index=False)

def save_queue(df: pd.DataFrame):
    df.to_parquet(QUEUE_PATH, index=False)

# ==============================================================================
# A/B TESTING & RATE LIMITS
# ==============================================================================
def is_holdout_group(member_id: str) -> bool:
    """Deterministically assign 10% of members to holdout (untreated) group using SHA256."""
    salt = "hotworx_ab_holdout_salt_2026"
    hash_object = hashlib.sha256((member_id + salt).encode("utf-8"))
    hash_hex = hash_object.hexdigest()
    val = int(hash_hex[-4:], 16)
    return (val % 10) == 0

def check_member_rate_limit(hashed_member_id: str, current_time: datetime.datetime) -> bool:
    """Check if the member received any active intervention in the past 7 days."""
    audit_df = load_audit_log()
    if audit_df.empty:
        return False
        
    seven_days_ago = current_time - datetime.timedelta(days=7)
    member_sends = audit_df[
        (audit_df["hashed_member_id"] == hashed_member_id) & 
        (audit_df["status"].isin(["Sent", "DryRun"]))
    ].copy()
    
    if member_sends.empty:
        return False
        
    member_sends["sent_at"] = pd.to_datetime(member_sends["sent_at"])
    latest_send = member_sends["sent_at"].max()
    return latest_send >= seven_days_ago

def check_global_rate_limit(current_time: datetime.datetime) -> int:
    """Count total sent messages in the last 1 hour. Return the count."""
    audit_df = load_audit_log()
    if audit_df.empty:
        return 0
        
    one_hour_ago = current_time - datetime.timedelta(hours=1)
    audit_df["sent_at"] = pd.to_datetime(audit_df["sent_at"])
    
    recent_sends = audit_df[
        (audit_df["sent_at"] >= one_hour_ago) & 
        (audit_df["status"] == "Sent")
    ]
    return len(recent_sends)

# ==============================================================================
# RULE ROUTER ENGINE
# ==============================================================================
def run_intervention_router():
    """Load latest scores, execute rules, rate limits, and record transactions."""
    initialize_parquet_files()
    
    scores_path = os.path.join(DATA_DIR, "churn_scores_daily.parquet")
    if not os.path.exists(scores_path):
        print(f"Error: Churn scores not found at {scores_path}. Run pipeline/scoring first.")
        sys.exit(1)
        
    if not os.path.exists(IDENTITY_PATH):
        print(f"Error: Secure Identity index not found at {IDENTITY_PATH}. Cannot resolve members.")
        sys.exit(1)
        
    live_mode = os.getenv("INTERVENTIONS_LIVE", "false").lower() == "true"
    current_time = datetime.datetime.now()
    run_id = uuid.uuid4().hex[:12]
    
    print("="*60)
    print(f"STARTING INTERVENTION ROUTER -- Live Mode: {live_mode}")
    print(f"Timestamp: {current_time.isoformat()}")
    print("="*60)
    
    email_adapter = HWCampaignAdapter(live_mode=live_mode)
    sms_adapter = TwilioAdapter(live_mode=live_mode)
    push_adapter = PushNotificationAdapter(live_mode=live_mode)
    
    scores_df = pd.read_parquet(scores_path)
    if scores_df.empty:
        print("No churn scores found to route.")
        return
        
    latest_score_date = scores_df["score_date"].max()
    print(f"Filtering scores for the latest snapshot date: {latest_score_date}")
    daily_scores = scores_df[scores_df["score_date"] == latest_score_date].copy()
    
    # Decrypted identity mappings loaded in-memory
    import secure_data
    identity_df = secure_data.read_encrypted_parquet(IDENTITY_PATH)
    
    merged_df = daily_scores.merge(identity_df, on="hashed_member_id")
    print(f"Loaded {len(merged_df)} active members to evaluate.")
    
    features_path = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
    features_df = pd.read_parquet(features_path)
    latest_features = features_df[features_df["date_day"] == latest_score_date][["hashed_member_id", "home_studio_id"]].drop_duplicates()
    merged_df = merged_df.merge(latest_features, on="hashed_member_id", how="left")
    
    audit_log = load_audit_log()
    queue = load_queue()

    # Precompute members messaged in the last 7 days
    seven_days_ago = current_time - datetime.timedelta(days=7)
    recently_messaged = set()
    if not audit_log.empty:
        recent = audit_log[audit_log["status"].isin(["Sent", "DryRun"])].copy()
        if not recent.empty:
            recent["sent_at"] = pd.to_datetime(recent["sent_at"])
            recently_messaged = set(recent[recent["sent_at"] >= seven_days_ago]["hashed_member_id"])
    
    # Track statistics (Phase 5 split: sent vs pending_calls)
    stats = {"evaluated": 0, "no_action": 0, "holdout": 0, "rate_limited": 0, "sent": 0, "pending_calls": 0, "failed": 0}

    new_audit_records = []
    new_queue_records = []

    prior_hourly_sent = check_global_rate_limit(current_time) if live_mode else 0
    in_run_sent = 0
    kill_switch_tripped = False

    for idx, member in merged_df.iterrows():
        stats["evaluated"] += 1
        member_id = member["member_id"]
        hashed_id = member["hashed_member_id"]
        name = member["name"]
        email = member["email"]
        phone = member["phone"]
        score = member["churn_probability"]
        tier = member["risk_tier"]
        studio_id = member["home_studio_id"] if pd.notna(member["home_studio_id"]) else "S01"
        
        # 1. Determine Action based on Risk Tier
        action_type = None
        action_details = ""
        message_body = ""
        
        if tier == "Low":
            stats["no_action"] += 1
            continue
            
        elif tier == "Medium":
            action_type = "Email"
            action_details = "Send: Re-engagement promotions & new class highlights email."
            message_body = f"Hi {name}, we noticed you haven't booked a session lately! Check out our new virtual trainers and book a slot today."
            
        elif tier == "High":
            action_type = "SMS"
            action_details = "Send: Push notification or personal SMS."
            message_body = f"Hey {name}! It's your coach at HOTWORX. We miss you in the sauna! Here's a voucher for a free retail recovery drink on your next session: HOTRECOVERY."
            
        elif tier == "Critical":
            action_type = "Call"
            action_details = "Action: Studio staff personal outreach call required immediately."
            message_body = f"URGENT: Call {name} ({phone}) to resolve account issues (e.g. failed payment or cancellation inquiries)."
            
        if not action_type:
            continue
            
        # 2. Check A/B Test Holdout Assignment (10%) -- RE-ORDERED before rate limit
        is_holdout = is_holdout_group(member_id)
        if is_holdout:
            stats["holdout"] += 1
            new_queue_records.append({
                "action_id": f"AC{run_id}{idx:04d}",
                "member_id": member_id,
                "hashed_member_id": hashed_id,
                "home_studio_id": studio_id,
                "score_date": latest_score_date,
                "risk_score": score,
                "risk_tier": tier,
                "action_type": action_type,
                "action_details": action_details + " (Holdout Group: Untreated)",
                "status": "Holdout",
                "created_at": current_time,
                "processed_at": current_time
            })
            new_audit_records.append({
                "audit_id": f"AU{run_id}{idx:04d}",
                "member_id": member_id,
                "hashed_member_id": hashed_id,
                "sent_at": current_time,
                "action_type": action_type,
                "status": "Holdout",
                "why_score": f"Score: {score:.4f} | Tier: {tier}",
                "message_body": message_body,
                "error_message": ""
            })
            continue

        # 3. Check Member-Level Rate Limit (1 msg per 7 days)
        is_limited = False
        if action_type in ["Email", "SMS", "Push"]:
            is_limited = hashed_id in recently_messaged
            
        if is_limited:
            stats["rate_limited"] += 1
            new_queue_records.append({
                "action_id": f"AC{run_id}{idx:04d}",
                "member_id": member_id,
                "hashed_member_id": hashed_id,
                "home_studio_id": studio_id,
                "score_date": latest_score_date,
                "risk_score": score,
                "risk_tier": tier,
                "action_type": action_type,
                "action_details": action_details + " (Rate Limited: Skipped)",
                "status": "RateLimited",
                "created_at": current_time,
                "processed_at": current_time
            })
            continue
            
        # 4. Trigger Outbound Service (Adapters)
        status = "Pending"
        error_msg = ""
        
        if live_mode and action_type in ["Email", "SMS"]:
            if prior_hourly_sent + in_run_sent >= GLOBAL_LIMIT_HOURLY:
                print(f"CRITICAL: Global hourly send limit reached ({prior_hourly_sent + in_run_sent}/{GLOBAL_LIMIT_HOURLY}). Kill switch engaged.")
                kill_switch_tripped = True
                break
        
        try:
            if action_type == "Call":
                status = "Pending"
            elif action_type == "Email":
                email_adapter.send_email(email, f"HOTWORX Update: We miss you, {name}!", message_body)
                status = "Sent" if live_mode else "DryRun"
            elif action_type == "SMS":
                sms_adapter.send_sms(phone, message_body)
                status = "Sent" if live_mode else "DryRun"
            elif action_type == "Push":
                push_adapter.send_push(member_id, "We miss you in the studio!", message_body)
                status = "Sent" if live_mode else "DryRun"

            if status == "Sent":
                in_run_sent += 1
            
            # Clean statistics tracking (pending_calls vs sent)
            if action_type == "Call":
                stats["pending_calls"] += 1
            else:
                stats["sent"] += 1
                
        except Exception as e:
            status = "Failed"
            error_msg = str(e)
            stats["failed"] += 1
            print(f"FAILED sending {action_type} to {member_id}: {error_msg}")
            
        new_queue_records.append({
            "action_id": f"AC{run_id}{idx:04d}",
            "member_id": member_id,
            "hashed_member_id": hashed_id,
            "home_studio_id": studio_id,
            "score_date": latest_score_date,
            "risk_score": score,
            "risk_tier": tier,
            "action_type": action_type,
            "action_details": action_details,
            "status": status,
            "created_at": current_time,
            "processed_at": current_time if status != "Pending" else None
        })
        
        new_audit_records.append({
            "audit_id": f"AU{run_id}{idx:04d}",
            "member_id": member_id,
            "hashed_member_id": hashed_id,
            "sent_at": current_time,
            "action_type": action_type,
            "status": status,
            "why_score": f"Score: {score:.4f} | Tier: {tier}",
            "message_body": message_body,
            "error_message": error_msg
        })
        
    if new_queue_records:
        new_q_df = pd.DataFrame(new_queue_records)
        queue = pd.concat([queue, new_q_df], ignore_index=True)
        save_queue(queue)
        
    if new_audit_records:
        new_a_df = pd.DataFrame(new_audit_records)
        audit_log = pd.concat([audit_log, new_a_df], ignore_index=True)
        save_audit_log(audit_log)
        
    print("\nROUTER COMPLETED.")
    print(f"Total Evaluated: {stats['evaluated']}")
    print(f"No Action (Low): {stats['no_action']}")
    print(f"A/B Holdout    : {stats['holdout']}")
    print(f"Rate Limited   : {stats['rate_limited']}")
    print(f"Pending Calls  : {stats['pending_calls']}")
    print(f"Queued/Sent    : {stats['sent']}")
    print(f"Failed         : {stats['failed']}")
    print("="*60)

    if kill_switch_tripped:
        raise RuntimeError(
            f"Global hourly send limit ({GLOBAL_LIMIT_HOURLY}) hit -- run halted after {in_run_sent} "
            "live send(s) this run. Audit and queue were flushed. Investigate before re-running."
        )

if __name__ == "__main__":
    run_intervention_router()
