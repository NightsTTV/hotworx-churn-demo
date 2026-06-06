import os
import uuid
import datetime
import numpy as np
import pandas as pd
from faker import Faker
import pyarrow as pa
import pyarrow.parquet as pq

# ==============================================================================
# CONSTANTS & CONFIGURATION
# ==============================================================================
SYNTHETIC_DATA = True  # Security Header marker
SEED = 42
NUM_STUDIOS = 10
NUM_MEMBERS = 5000
START_DATE = datetime.date(2024, 1, 1)
END_DATE = datetime.date(2026, 6, 1)
DATA_DIR = "./data"

# Initialize Random States
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

# Make output directory if not exists
os.makedirs(DATA_DIR, exist_ok=True)

# Helper function to write Parquet with Custom Metadata
def write_parquet_with_metadata(df, filepath):
    table = pa.Table.from_pandas(df)
    existing_metadata = table.schema.metadata or {}
    # Merge existing metadata with our synthetic security note
    custom_metadata = {
        **{k.decode('utf-8') if isinstance(k, bytes) else k: v.decode('utf-8') if isinstance(v, bytes) else v for k, v in existing_metadata.items()},
        "SYNTHETIC_DATA": "TRUE",
        "GENERATOR_VERSION": "1.0",
        "GENERATION_DATE": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    # Encode values to bytes
    metadata_bytes = {k.encode('utf-8'): v.encode('utf-8') for k, v in custom_metadata.items()}
    table = table.replace_schema_metadata(metadata_bytes)
    pq.write_table(table, filepath)
    print(f"Saved {filepath} with metadata: {custom_metadata}")

# Helper to generate dates with seasonality (January spikes, summer dips)
def generate_seasonal_join_dates(start_date, end_date, n_samples):
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    # Weights for each month to represent seasonality
    # High in January/February, Low in Summer (June, July, August)
    month_weights = {
        1: 1.8, 2: 1.5, 3: 1.1, 4: 1.0, 5: 0.9, 6: 0.5,
        7: 0.4, 8: 0.5, 9: 1.0, 10: 1.0, 11: 0.8, 12: 0.8
    }
    weights = np.array([month_weights[d.month] for d in date_range])
    probs = weights / weights.sum()
    chosen_dates = np.random.choice(date_range, size=n_samples, p=probs)
    return [pd.to_datetime(d).date() for d in chosen_dates]

# ==============================================================================
# PHASE 1: GENERATORS FOR DATA TABLES
# ==============================================================================

# 1. Studio Generation
def generate_studios():
    print("Generating studios...")
    studio_names = [
        "Studio Nebula", "Studio Zephyr", "Studio Sol", "Studio Aurora", 
        "Studio Zenith", "Studio Apex", "Studio Nova", "Studio Echo", 
        "Studio Pulse", "Studio Eclipse"
    ]
    studios = []
    for i in range(NUM_STUDIOS):
        studio_id = f"S{i+1:02d}"
        studios.append({
            "studio_id": studio_id,
            "studio_name": studio_names[i],
            "address": fake.street_address(),
            "city": fake.city(),
            "state": fake.state_abbr(),
            "zip_code": fake.zipcode(),
            "is_synthetic": SYNTHETIC_DATA
        })
    return pd.DataFrame(studios)

# 2. Member & Ground Truth Generation
def generate_members_and_ground_truth(studios_df):
    print("Generating members...")
    members = []
    ground_truth = []
    
    # Generate join dates
    join_dates = generate_seasonal_join_dates(START_DATE, END_DATE - datetime.timedelta(days=30), NUM_MEMBERS)
    studio_ids = studios_df["studio_id"].tolist()
    
    # Cohort distribution
    cohort_choices = ["steady", "declining", "sudden_drop"]
    cohort_weights = [0.70, 0.20, 0.10]
    member_cohorts = np.random.choice(cohort_choices, size=NUM_MEMBERS, p=cohort_weights)
    
    for i in range(NUM_MEMBERS):
        member_id = f"M{i+1:04d}"
        cohort = member_cohorts[i]
        join_date = join_dates[i]
        
        # Gender and Age Profile
        gender = np.random.choice(["F", "M", "Other"], p=[0.65, 0.30, 0.05])
        dob = fake.date_of_birth(minimum_age=18, maximum_age=70)
        
        # Churn Decision
        churned = False
        churn_date = None
        churn_risk = "low"
        
        # Calculate maximum possible tenure in days
        max_tenure_days = (END_DATE - join_date).days
        
        if cohort == "steady":
            # 2% baseline random churn over simulation window
            if np.random.rand() < 0.02 and max_tenure_days > 60:
                churned = True
                churn_days = np.random.randint(60, max_tenure_days)
                churn_date = join_date + datetime.timedelta(days=churn_days)
            churn_risk = "low"
            
        elif cohort == "declining":
            # 85% churn rate for gradually declining
            if np.random.rand() < 0.85 and max_tenure_days > 90:
                churned = True
                churn_days = np.random.randint(90, max_tenure_days)
                churn_date = join_date + datetime.timedelta(days=churn_days)
                churn_risk = "high"
            else:
                churn_risk = "medium"
                
        elif cohort == "sudden_drop":
            # 100% churn rate
            churned = True
            # Sudden dropper triggers billing failure, then cancels 14 days later
            # Must fail billing at least 15 days before END_DATE
            if max_tenure_days > 34:
                billing_fail_days = np.random.randint(20, max_tenure_days - 14)
                failed_billing_date = join_date + datetime.timedelta(days=billing_fail_days)
                churn_date = failed_billing_date + datetime.timedelta(days=14)
            else:
                churn_date = END_DATE - datetime.timedelta(days=1)
            churn_risk = "critical"


        # Generate fake names securely
        name = fake.name()
        first_name = name.split(" ")[0]
        email = f"{first_name.lower()}.{fake.word()}.{i}@synthetic-hotworx-demo.com"
        phone = f"555-{np.random.randint(100, 999)}-{np.random.randint(1000, 9999)}"
        
        members.append({
            "member_id": member_id,
            "name": name,
            "email": email,
            "phone": phone,
            "gender": gender,
            "dob": dob,
            "home_studio_id": np.random.choice(studio_ids),
            "join_date": join_date,
            "is_synthetic": SYNTHETIC_DATA
        })
        
        ground_truth.append({
            "member_id": member_id,
            "cohort": cohort,
            "churned": churned,
            "churn_date": churn_date,
            "churn_risk": churn_risk,
            "is_synthetic": SYNTHETIC_DATA
        })
        
    return pd.DataFrame(members), pd.DataFrame(ground_truth)

# 3. Membership Generation
def generate_memberships(members_df, ground_truth_df):
    print("Generating memberships...")
    memberships = []
    
    tiers = ["Basic", "VIP", "Premium"]
    tier_prices = {"Basic": 59.00, "VIP": 99.00, "Premium": 129.00}
    tier_probs = [0.50, 0.40, 0.10]
    
    for idx, row in members_df.iterrows():
        member_id = row["member_id"]
        studio_id = row["home_studio_id"]
        join_date = row["join_date"]
        
        gt_row = ground_truth_df[ground_truth_df["member_id"] == member_id].iloc[0]
        churned = gt_row["churned"]
        churn_date = gt_row["churn_date"]
        
        tier = np.random.choice(tiers, p=tier_probs)
        price = tier_prices[tier]
        
        membership_id = f"MS{idx+1:04d}"
        status = "Cancelled" if churned else "Active"
        
        memberships.append({
            "membership_id": membership_id,
            "member_id": member_id,
            "studio_id": studio_id,
            "membership_tier": tier,
            "monthly_price": price,
            "start_date": join_date,
            "end_date": churn_date if churned else None,
            "status": status,
            "is_synthetic": SYNTHETIC_DATA
        })
        
    return pd.DataFrame(memberships)

# 4. Sessions (Infrared Sauna Bookings)
def generate_sessions(members_df, ground_truth_df):
    print("Generating sessions...")
    sessions = []
    session_types = ["Hot Yoga", "Hot Pilates", "Hot Cycle", "Hot Row", "Hot Barre", "Hot Core", "Hot Iso", "Hot Blast"]
    session_weights = [0.20, 0.15, 0.20, 0.15, 0.10, 0.10, 0.05, 0.05]
    
    # Peak hour templates
    peak_hours = [6, 7, 8, 17, 18, 19]
    offpeak_hours = [9, 10, 11, 12, 13, 14, 15, 16, 20, 21, 22]
    
    session_idx = 1
    
    for idx, row in members_df.iterrows():
        member_id = row["member_id"]
        studio_id = row["home_studio_id"]
        join_date = row["join_date"]
        
        gt_row = ground_truth_df[ground_truth_df["member_id"] == member_id].iloc[0]
        cohort = gt_row["cohort"]
        churned = gt_row["churned"]
        churn_date = gt_row["churn_date"]
        
        end_obs = churn_date if churned else END_DATE
        total_weeks = max(1, int((end_obs - join_date).days / 7))
        
        # Determine baseline weekly sessions
        if cohort == "steady":
            base_sessions_per_week = np.random.uniform(2.5, 4.5)
        elif cohort == "declining":
            base_sessions_per_week = np.random.uniform(2.5, 4.0)
            # Declining starts decaying in the last 12 weeks of their active period
            decline_start_week = max(0, total_weeks - 12)
        else: # sudden_drop
            base_sessions_per_week = np.random.uniform(2.5, 4.0)
            # Fails billing 14 days prior to churn_date
            billing_fail_week = max(0, total_weeks - 2)

        for w in range(total_weeks):
            week_start = join_date + datetime.timedelta(days=w*7)
            
            # 1. Seasonality Multiplier (Jan/Feb boost, Jun/Jul/Aug dip)
            month = week_start.month
            season_mult = 1.0
            if month in [1, 2]:
                season_mult = 1.25
            elif month in [6, 7, 8]:
                season_mult = 0.80
                
            # 2. Cohort Decline Multiplier
            cohort_mult = 1.0
            if cohort == "declining" and w >= decline_start_week:
                # Linear decay from 1.0 to 0.05
                weeks_in_decline = total_weeks - decline_start_week
                progress = (w - decline_start_week) / weeks_in_decline
                cohort_mult = max(0.05, 1.0 - progress)
            elif cohort == "sudden_drop" and w >= billing_fail_week:
                cohort_mult = 0.0  # Completely stops booking after billing failure

            # Target sessions count
            target_weekly = base_sessions_per_week * season_mult * cohort_mult
            if target_weekly <= 0:
                continue
                
            num_weekly_sessions = np.random.poisson(target_weekly)
            
            for s in range(num_weekly_sessions):
                day_offset = np.random.randint(0, 7)
                sess_date = week_start + datetime.timedelta(days=day_offset)
                if sess_date >= end_obs:
                    continue
                    
                # Time slots
                p_raw = [0.12]*len(peak_hours) + [0.025]*len(offpeak_hours)
                p_norm = [p / sum(p_raw) for p in p_raw]
                hour = np.random.choice(peak_hours + offpeak_hours, p=p_norm)
                minute = np.random.choice([0, 15, 30, 45])
                sess_time = datetime.time(int(hour), int(minute))
                sess_timestamp = datetime.datetime.combine(sess_date, sess_time)
                
                # Attendance probability
                if cohort == "steady":
                    att_prob = 0.92
                elif cohort == "declining":
                    # Attendance drops along with sessions
                    att_prob = max(0.40, 0.90 - (0.50 * (w / total_weeks)))
                else: # sudden drop
                    att_prob = 0.90
                    
                attended = np.random.rand() < att_prob
                temp = float(np.random.uniform(120.0, 130.0))
                
                sessions.append({
                    "session_id": f"SESS{session_idx:07d}",
                    "member_id": member_id,
                    "studio_id": studio_id,
                    "session_type": np.random.choice(session_types, p=session_weights),
                    "scheduled_at": sess_timestamp,
                    "attended": attended,
                    "sauna_temp_f": temp,
                    "is_synthetic": SYNTHETIC_DATA
                })
                session_idx += 1
                
    return pd.DataFrame(sessions)

# 5. Transactions (Membership Payments & Retail Purchases)
def generate_transactions(members_df, memberships_df, ground_truth_df):
    print("Generating transactions...")
    transactions = []
    retail_items = [
        ("Water Bottle", 3.00), ("Yoga Mat", 55.00), ("HOTWORX Towel", 25.00), 
        ("Performance Tee", 35.00), ("Energy Drink", 4.00), ("Sauna Band", 15.00)
    ]
    retail_probs = [0.50, 0.05, 0.10, 0.10, 0.20, 0.05]
    
    tx_idx = 1
    
    for idx, member in members_df.iterrows():
        member_id = member["member_id"]
        studio_id = member["home_studio_id"]
        join_date = member["join_date"]
        
        gt_row = ground_truth_df[ground_truth_df["member_id"] == member_id].iloc[0]
        cohort = gt_row["cohort"]
        churned = gt_row["churned"]
        churn_date = gt_row["churn_date"]
        
        membership = memberships_df[memberships_df["member_id"] == member_id].iloc[0]
        monthly_price = membership["monthly_price"]
        
        end_obs = churn_date if churned else END_DATE
        
        # 1. Monthly Recurring Billing
        curr_billing_date = join_date

        # For the sudden_drop cohort the recurring charge fails 14 days before
        # cancellation. We stop normal (paid) billing at that point and inject an
        # explicit Failed charge after the loop, guaranteeing EVERY sudden_drop member
        # carries the billing-failure signal. (Previously ~55% were missing it because
        # no monthly cycle happened to land in the final 14-day window.)
        sudden_fail_date = None
        paid_billing_end = end_obs
        if cohort == "sudden_drop" and churned and churn_date is not None:
            sudden_fail_date = churn_date - datetime.timedelta(days=14)
            if sudden_fail_date <= join_date:
                sudden_fail_date = join_date + datetime.timedelta(days=2)
            paid_billing_end = min(end_obs, sudden_fail_date)

        while curr_billing_date < paid_billing_end:
            status = "Paid"

            if cohort == "steady":
                # 0.5% chance of a random failure that is immediately resolved
                if np.random.rand() < 0.005:
                    # Add failed record
                    transactions.append({
                        "transaction_id": f"TX{tx_idx:07d}",
                        "member_id": member_id,
                        "studio_id": studio_id,
                        "transaction_date": curr_billing_date,
                        "amount": monthly_price,
                        "transaction_type": "Membership Fee",
                        "status": "Failed",
                        "is_synthetic": SYNTHETIC_DATA
                    })
                    tx_idx += 1
                    # Followed by a paid retry transaction 2 days later
                    transactions.append({
                        "transaction_id": f"TX{tx_idx:07d}",
                        "member_id": member_id,
                        "studio_id": studio_id,
                        "transaction_date": curr_billing_date + datetime.timedelta(days=2),
                        "amount": monthly_price,
                        "transaction_type": "Membership Fee",
                        "status": "Paid",
                        "is_synthetic": SYNTHETIC_DATA
                    })
                    tx_idx += 1
                    status = None  # Skip standard log to avoid duplication

            if status is not None:
                transactions.append({
                    "transaction_id": f"TX{tx_idx:07d}",
                    "member_id": member_id,
                    "studio_id": studio_id,
                    "transaction_date": curr_billing_date,
                    "amount": monthly_price,
                    "transaction_type": "Membership Fee",
                    "status": status,
                    "is_synthetic": SYNTHETIC_DATA
                })
                tx_idx += 1

            # Increment monthly billing cycle (simple, overflow-safe month addition)
            year = curr_billing_date.year + (curr_billing_date.month // 12)
            month = (curr_billing_date.month % 12) + 1
            day = min(curr_billing_date.day, 28)
            curr_billing_date = datetime.date(year, month, day)

        # Inject the guaranteed billing failure that precipitates the sudden drop.
        if sudden_fail_date is not None and sudden_fail_date < end_obs:
            transactions.append({
                "transaction_id": f"TX{tx_idx:07d}",
                "member_id": member_id,
                "studio_id": studio_id,
                "transaction_date": sudden_fail_date,
                "amount": monthly_price,
                "transaction_type": "Membership Fee",
                "status": "Failed",
                "is_synthetic": SYNTHETIC_DATA
            })
            tx_idx += 1

        # 2. Retail Purchases (Occasional purchases based on cohort and time)
        # Steady members buy retail occasionally (e.g., once every 30 days)
        # Declining buy less and less
        total_days = (end_obs - join_date).days
        if total_days > 15:
            num_retail_tx = 0
            if cohort == "steady":
                num_retail_tx = np.random.poisson(total_days / 45.0)
            elif cohort == "declining":
                num_retail_tx = np.random.poisson(total_days / 90.0)
            else: # sudden drop
                num_retail_tx = np.random.poisson(total_days / 50.0)
                
            for r in range(num_retail_tx):
                offset_days = np.random.randint(5, total_days)
                tx_date = join_date + datetime.timedelta(days=offset_days)
                
                # Check if this falls in a decline phase for declining members
                if cohort == "declining" and (end_obs - tx_date).days < 60:
                    if np.random.rand() < 0.7:
                        continue # Skip purchase during decline
                        
                item_name, item_price = retail_items[np.random.choice(len(retail_items), p=retail_probs)]
                
                transactions.append({
                    "transaction_id": f"TX{tx_idx:07d}",
                    "member_id": member_id,
                    "studio_id": studio_id,
                    "transaction_date": tx_date,
                    "amount": item_price,
                    "transaction_type": f"Retail - {item_name}",
                    "status": "Paid",
                    "is_synthetic": SYNTHETIC_DATA
                })
                tx_idx += 1

    return pd.DataFrame(transactions)

# 6. App Events
def generate_app_events(members_df, ground_truth_df):
    print("Generating app events...")
    events = []
    event_types = ["open_app", "book_session", "cancel_session", "view_metrics", "update_profile"]
    
    event_idx = 1
    
    for idx, member in members_df.iterrows():
        member_id = member["member_id"]
        join_date = member["join_date"]
        
        gt_row = ground_truth_df[ground_truth_df["member_id"] == member_id].iloc[0]
        cohort = gt_row["cohort"]
        churned = gt_row["churned"]
        churn_date = gt_row["churn_date"]
        
        end_obs = churn_date if churned else END_DATE
        total_days = (end_obs - join_date).days
        
        # Weekly event counts
        total_weeks = max(1, total_days // 7)
        device = np.random.choice(["iOS", "Android"], p=[0.72, 0.28])
        
        for w in range(total_weeks):
            week_start = join_date + datetime.timedelta(days=w*7)
            
            # Events scale based on cohort behavior
            if cohort == "steady":
                base_weekly = np.random.uniform(10, 20)
            elif cohort == "declining":
                # Decays linearly to near zero in the final weeks
                base_weekly = np.random.uniform(8, 16)
                decline_progress = w / total_weeks
                base_weekly = max(0.5, base_weekly * (1.0 - decline_progress * 0.95))
            else: # sudden_drop
                base_weekly = np.random.uniform(8, 16)
                # After billing failure (2 weeks before churn), app events plunge
                if w >= total_weeks - 2:
                    base_weekly = np.random.uniform(1, 3) # only log in to see check failures
            
            num_events = np.random.poisson(base_weekly)
            for e in range(num_events):
                day_offset = np.random.randint(0, 7)
                event_date = week_start + datetime.timedelta(days=day_offset)
                if event_date >= end_obs:
                    continue
                    
                hour = np.random.randint(5, 23)
                minute = np.random.randint(0, 60)
                event_time = datetime.time(hour, minute)
                event_ts = datetime.datetime.combine(event_date, event_time)
                
                # Pick event type
                event_type = np.random.choice(event_types, p=[0.45, 0.25, 0.05, 0.20, 0.05])
                
                events.append({
                    "event_id": f"EV{event_idx:07d}",
                    "member_id": member_id,
                    "event_type": event_type,
                    "event_timestamp": event_ts,
                    "device_os": device,
                    "is_synthetic": SYNTHETIC_DATA
                })
                event_idx += 1
                
    return pd.DataFrame(events)

# 7. AI Coach Chats (Motivation, routines, and freeze queries)
def generate_ai_coach_chats(members_df, ground_truth_df):
    print("Generating AI coach chats...")
    chats = []
    
    # Pre-defined chat script database matching user intents
    steady_prompts = [
        ("How can I improve my muscle recovery after Hot Cycle?", "Cycle workouts are high intensity! The infrared heat is excellent for dilating blood vessels to speed recovery. Make sure to hydrate and supplement with electrolytes, and schedule a Hot Iso session for active recovery."),
        ("What is the optimal temperature for Hot Yoga?", "We set our saunas to 125°F for Hot Yoga. This maximizes sweat and flexibility. If you feel too hot, make sure to sit on your towel and take slow, deep breaths."),
        ("Can I book double sessions?", "Absolutely! A popular combination is an isometric workout (like Hot Yoga) followed immediately by a HIIT workout (like Hot Cycle). Be sure to double your water intake."),
        ("Is it normal to sweat this much?", "Yes! Working out in an infrared sauna can generate up to 2-3x the sweat volume of a standard workout. It's excellent for detoxification!"),
        ("How do I build core strength faster?", "Our Hot Core and Hot Pilates classes are specifically designed for rapid core strengthening. Try incorporating 2 core sessions weekly into your schedule.")
    ]
    
    declining_prompts = [
        ("I'm feeling unmotivated lately, what should I do?", "It's completely normal to hit a wall. Try reducing your session duration or switching to a lower intensity class like Hot Core. Getting through the door is the hardest part!"),
        ("How do I temporarily freeze my membership?", "You can place your account on a temporary freeze for up to 3 months. To do this, please speak to the front desk at your home studio to fill out a brief freeze form."),
        ("I'm not seeing results, should I stop?", "Results take time and consistency. If weight loss is your goal, infrared helps burn calories, but sleep and nutrition are key partners. Let's aim for 2 sessions a week to start."),
        ("My schedule has changed. Can I cancel online?", "We'd hate to see you go! Membership modifications, including cancellations, must be completed in-person at your home studio with a 30-day notice."),
        ("How long does the freeze take to activate?", "Once requested in-person, a freeze can go into effect at the start of your next billing cycle.")
    ]
    
    sudden_drop_prompts = [
        ("Why was my card declined today?", "We encountered an issue processing your recurring payment. Please verify your billing details in the app or contact your studio to update your card."),
        ("My account says suspended. How do I fix it?", "Accounts are auto-suspended when payment is overdue. Once you update your payment information, access will be restored immediately."),
        ("How do I cancel my subscription right now?", "To cancel, you must submit a written cancellation request in-person at your home studio. Please note our standard 30-day cancellation notice policy."),
        ("Can I update my card over the phone?", "Yes, you can call your home studio to update your payment details, or do it securely inside the account portal under Billing info.")
    ]
    
    chat_idx = 1
    
    for idx, member in members_df.iterrows():
        member_id = member["member_id"]
        join_date = member["join_date"]
        
        gt_row = ground_truth_df[ground_truth_df["member_id"] == member_id].iloc[0]
        cohort = gt_row["cohort"]
        churned = gt_row["churned"]
        churn_date = gt_row["churn_date"]
        
        end_obs = churn_date if churned else END_DATE
        total_days = (end_obs - join_date).days
        
        # Decide if this member chats at all
        # 40% of steady members chat, 60% of declining members (asking about freezes/motivation), 80% of sudden drop (billing queries)
        chat_prob = 0.40 if cohort == "steady" else (0.60 if cohort == "declining" else 0.80)
        
        if np.random.rand() > chat_prob or total_days < 10:
            continue
            
        # Select prompt bank
        if cohort == "steady":
            prompts = steady_prompts
            num_chats = np.random.randint(1, 4)
        elif cohort == "declining":
            prompts = declining_prompts
            num_chats = np.random.randint(1, 3)
        else:
            prompts = sudden_drop_prompts
            num_chats = 1
            
        for c in range(num_chats):
            # Pick a date for chat
            if cohort == "sudden_drop":
                # Chat happens right after billing failure (around 10-13 days before churn)
                chat_offset = max(5, total_days - np.random.randint(10, 13))
            elif cohort == "declining":
                # Chat happens in decline phase (last 30 days)
                chat_offset = max(5, total_days - np.random.randint(5, 45))
            else:
                # Random time
                chat_offset = np.random.randint(5, total_days)
                
            chat_date = join_date + datetime.timedelta(days=chat_offset)
            if chat_date >= end_obs:
                continue
                
            hour = np.random.randint(8, 20)
            minute = np.random.randint(0, 60)
            chat_ts = datetime.datetime.combine(chat_date, datetime.time(hour, minute))
            
            prompt_text, response_text = prompts[np.random.choice(len(prompts))]
            
            # Message 1: Member
            chats.append({
                "chat_id": f"CH{chat_idx:07d}",
                "member_id": member_id,
                "timestamp": chat_ts,
                "sender": "member",
                "message_text": prompt_text,
                "is_synthetic": SYNTHETIC_DATA
            })
            
            # Message 2: Coach (1-2 minutes later)
            chats.append({
                "chat_id": f"CH{chat_idx:07d}",
                "member_id": member_id,
                "timestamp": chat_ts + datetime.timedelta(minutes=np.random.randint(1, 3)),
                "sender": "coach",
                "message_text": response_text,
                "is_synthetic": SYNTHETIC_DATA
            })
            chat_idx += 1
            
    return pd.DataFrame(chats)

# 8. Email Events
def generate_email_events(members_df, ground_truth_df):
    print("Generating email events...")
    emails = []
    
    campaigns = [
        ("Weekly Workout Wrap-up", 0.7, 0.2),
        ("Infrared Sauna Tips & Tricks", 0.5, 0.1),
        ("Monthly Studio Newsletter", 0.4, 0.05),
        ("Refer a Friend Promo", 0.3, 0.05)
    ]
    
    email_idx = 1
    
    for idx, member in members_df.iterrows():
        member_id = member["member_id"]
        join_date = member["join_date"]
        
        gt_row = ground_truth_df[ground_truth_df["member_id"] == member_id].iloc[0]
        cohort = gt_row["cohort"]
        churned = gt_row["churned"]
        churn_date = gt_row["churn_date"]
        
        end_obs = churn_date if churned else END_DATE
        total_days = (end_obs - join_date).days
        total_weeks = max(1, total_days // 7)
        
        for w in range(total_weeks):
            week_start = join_date + datetime.timedelta(days=w*7)
            
            # Send an email once a week
            camp_name, base_open, base_click = campaigns[np.random.choice(len(campaigns))]
            
            # Adjust open rate based on cohort & lifetime
            if cohort == "steady":
                open_prob = base_open * 1.1
                click_prob = base_click * 1.2
            elif cohort == "declining":
                # Decay open rate over time
                decay = max(0.1, 1.0 - (w / total_weeks))
                open_prob = base_open * decay
                click_prob = base_click * decay
            else: # sudden drop
                open_prob = base_open
                click_prob = base_click
                # After billing failure, emails aren't opened
                if w >= total_weeks - 2:
                    open_prob = 0.05
                    click_prob = 0.0
            
            sent_date = week_start + datetime.timedelta(days=np.random.randint(0, 7))
            if sent_date >= end_obs:
                continue
                
            sent_ts = datetime.datetime.combine(sent_date, datetime.time(np.random.randint(8, 18), np.random.randint(0, 60)))
            
            opened = np.random.rand() < open_prob
            clicked = opened and (np.random.rand() < (click_prob / open_prob if open_prob > 0 else 0))
            
            status = "Clicked" if clicked else ("Opened" if opened else "Sent")
            
            emails.append({
                "email_id": f"EM{email_idx:07d}",
                "member_id": member_id,
                "subject": camp_name,
                "sent_at": sent_ts,
                "status": status,
                "is_synthetic": SYNTHETIC_DATA
            })
            email_idx += 1
            
    return pd.DataFrame(emails)

# ==============================================================================
# PIPELINE EXECUTION & VERIFICATION
# ==============================================================================
def main():
    print("==================================================")
    print("STARTING SYNTHETIC DATA GENERATION PIPELINE")
    print(f"Goal: {NUM_MEMBERS} members across {NUM_STUDIOS} studios")
    print(f"Simulation Range: {START_DATE} to {END_DATE}")
    print("==================================================")
    
    # 1. Run Generators
    studios_df = generate_studios()
    members_df, ground_truth_df = generate_members_and_ground_truth(studios_df)
    memberships_df = generate_memberships(members_df, ground_truth_df)
    sessions_df = generate_sessions(members_df, ground_truth_df)
    transactions_df = generate_transactions(members_df, memberships_df, ground_truth_df)
    app_events_df = generate_app_events(members_df, ground_truth_df)
    chats_df = generate_ai_coach_chats(members_df, ground_truth_df)
    emails_df = generate_email_events(members_df, ground_truth_df)
    
    print("\n--------------------------------------------------")
    print("GENERATION RUN COMPLETED. STARTING INTEGRITY CHECKS...")
    print("--------------------------------------------------")
    
    # 2. Assertions & Validation Checks
    # Check row counts
    assert len(studios_df) == NUM_STUDIOS, f"Studio count error: {len(studios_df)}"
    assert len(members_df) == NUM_MEMBERS, f"Member count error: {len(members_df)}"
    assert len(memberships_df) == NUM_MEMBERS, f"Membership count error: {len(memberships_df)}"
    assert len(ground_truth_df) == NUM_MEMBERS, f"Ground Truth count error: {len(ground_truth_df)}"
    
    # Check foreign key integrity
    # Members belong to valid studios
    assert members_df["home_studio_id"].isin(studios_df["studio_id"]).all(), "Failing FK: members -> studios"
    # Memberships belong to valid members and studios
    assert memberships_df["member_id"].isin(members_df["member_id"]).all(), "Failing FK: memberships -> members"
    assert memberships_df["studio_id"].isin(studios_df["studio_id"]).all(), "Failing FK: memberships -> studios"
    # Sessions belong to valid members and studios
    assert sessions_df["member_id"].isin(members_df["member_id"]).all(), "Failing FK: sessions -> members"
    assert sessions_df["studio_id"].isin(studios_df["studio_id"]).all(), "Failing FK: sessions -> studios"
    # Transactions belong to valid members and studios
    assert transactions_df["member_id"].isin(members_df["member_id"]).all(), "Failing FK: transactions -> members"
    assert transactions_df["studio_id"].isin(studios_df["studio_id"]).all(), "Failing FK: transactions -> studios"
    # App Events belong to valid members
    assert app_events_df["member_id"].isin(members_df["member_id"]).all(), "Failing FK: app_events -> members"
    # Chats belong to valid members
    assert chats_df["member_id"].isin(members_df["member_id"]).all(), "Failing FK: chats -> members"
    # Emails belong to valid members
    assert emails_df["member_id"].isin(members_df["member_id"]).all(), "Failing FK: emails -> members"
    
    # Check is_synthetic columns are present and strictly True
    for df_name, df in [
        ("studios", studios_df), ("members", members_df), ("memberships", memberships_df),
        ("sessions", sessions_df), ("transactions", transactions_df), ("app_events", app_events_df),
        ("chats", chats_df), ("emails", emails_df), ("ground_truth", ground_truth_df)
    ]:
        assert "is_synthetic" in df.columns, f"is_synthetic column missing in {df_name}"
        assert df["is_synthetic"].all() == True, f"Non-synthetic record found in {df_name}"
        
    # Check Specific Cohort/Billing Cancellations Correlation
    # Every sudden_drop member MUST carry a billing-failure signal. We check PER-MEMBER
    # coverage, not a global >0 count (which previously masked ~55% of the cohort having
    # no failed payment at all).
    sd_ids = set(ground_truth_df[ground_truth_df["cohort"] == "sudden_drop"]["member_id"])
    sd_with_fail = set(
        transactions_df[
            (transactions_df["member_id"].isin(sd_ids)) & (transactions_df["status"] == "Failed")
        ]["member_id"]
    )
    sd_coverage = len(sd_with_fail) / len(sd_ids) if sd_ids else 0.0
    print(f"sudden_drop billing-failure coverage: {sd_coverage:.1%} ({len(sd_with_fail)}/{len(sd_ids)})")
    assert sd_coverage >= 0.99, f"DQ Failure: sudden_drop billing-failure coverage too low: {sd_coverage:.1%}"
    print("FK and Integrity checks passed successfully!")
    
    # Print table summaries
    print("\nTable Statistics:")
    print(f"- Studios: {len(studios_df)} rows")
    print(f"- Members: {len(members_df)} rows")
    print(f"- Memberships: {len(memberships_df)} rows")
    print(f"- Sessions: {len(sessions_df)} rows")
    print(f"- Transactions: {len(transactions_df)} rows")
    print(f"- App Events: {len(app_events_df)} rows")
    print(f"- AI Coach Chats: {len(chats_df)} rows")
    print(f"- Email Events: {len(emails_df)} rows")
    print(f"- Ground Truth: {len(ground_truth_df)} rows")

    # 3. Write tables to Parquet with security headers
    print("\nWriting Parquet files to local data/ directory...")
    write_parquet_with_metadata(studios_df, os.path.join(DATA_DIR, "studios.parquet"))
    write_parquet_with_metadata(members_df, os.path.join(DATA_DIR, "members.parquet"))
    write_parquet_with_metadata(memberships_df, os.path.join(DATA_DIR, "memberships.parquet"))
    write_parquet_with_metadata(sessions_df, os.path.join(DATA_DIR, "sessions.parquet"))
    write_parquet_with_metadata(transactions_df, os.path.join(DATA_DIR, "transactions.parquet"))
    write_parquet_with_metadata(app_events_df, os.path.join(DATA_DIR, "app_events.parquet"))
    write_parquet_with_metadata(chats_df, os.path.join(DATA_DIR, "ai_coach_chats.parquet"))
    write_parquet_with_metadata(emails_df, os.path.join(DATA_DIR, "email_events.parquet"))
    write_parquet_with_metadata(ground_truth_df, os.path.join(DATA_DIR, "ground_truth.parquet"))
    
    print("\n==================================================")
    print("SYNTHETIC DATA PIPELINE RUN COMPLETED SUCCESSFULLY")
    print("==================================================")

if __name__ == "__main__":
    main()
