import os
import sys
import duckdb
import pandas as pd

DATA_DIR = "./data"

def query_member(member_id):
    identity_path = os.path.join(DATA_DIR, "int_member_identity.parquet")
    features_path = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
    
    if not os.path.exists(identity_path) or not os.path.exists(features_path):
        print("Error: Feature tables do not exist. Please run 'python run_pipeline.py' first.")
        sys.exit(1)
        
    import secure_data
    df_identity = secure_data.read_encrypted_parquet(identity_path)
    
    con = duckdb.connect(database=':memory:')
    con.register("identity", df_identity)
    con.execute(f"CREATE TEMPORARY VIEW features AS SELECT * FROM read_parquet('{features_path}');")
    
    # 1. Look up identity
    member = con.execute("SELECT * FROM identity WHERE member_id = ?", (member_id,)).fetchone()
    
    if not member:
        print(f"Error: Member ID '{member_id}' not found.")
        sys.exit(1)
        
    raw_id, hashed_id, name, email, phone = member
    
    print("\n" + "="*50)
    print("RESOLVED MEMBER IDENTITY (RESTRICTED PII ACCESS)")
    print("="*50)
    print(f"Raw Member ID      : {raw_id}")
    print(f"Hashed Surrogate ID: {hashed_id}")
    print(f"Full Name          : {name}")
    print(f"Email Address      : {email}")
    print(f"Phone Number       : {phone}")
    print("="*50)
    
    # 2. Fetch feature history (limit to a sample of days, e.g., the last 15 days of activity)
    print("\nDE-IDENTIFIED DAILY FEATURE PROFILE (FIRST 5 AND LAST 10 ACTIVE DAYS)")
    print("="*120)
    
    df = con.execute("""
        SELECT 
          date_day,
          age,
          gender,
          membership_tier,
          monthly_price,
          tenure_days,
          sessions_booked_30d,
          sessions_attended_30d,
          avg_sauna_temp_30d,
          days_since_last_session,
          retail_spend_30d,
          last_recurring_payment_failed,
          failed_payments_count_30d,
          app_logins_30d,
          coach_chat_count_30d,
          has_cancellation_query_30d,
          is_churned_14d
        FROM features 
        WHERE hashed_member_id = ?
        ORDER BY date_day
    """, (hashed_id,)).df()
    
    if df.empty:
        print("No daily feature history found for this member.")
        return
        
    # Print statistics
    total_days = len(df)
    print(f"Total days active in feature store: {total_days} days")
    print(f"Active date range: {df['date_day'].min()} to {df['date_day'].max()}")
    print("="*120)
    
    # Format and print rows
    cols_to_print = [
        'date_day', 'tenure_days', 'sessions_booked_30d', 'sessions_attended_30d', 
        'avg_sauna_temp_30d', 'days_since_last_session', 'last_recurring_payment_failed', 
        'app_logins_30d', 'coach_chat_count_30d', 'has_cancellation_query_30d', 'is_churned_14d'
    ]
    
    # Select first 5 and last 10 rows to show transition
    if len(df) <= 15:
        sub_df = df[cols_to_print]
    else:
        sub_df = pd.concat([df.head(5), df.tail(10)])[cols_to_print]
        
    # Pretty print
    print(sub_df.to_string(index=False))
    print("="*120)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python query_demo.py <MEMBER_ID>")
        print("Example: python query_demo.py M0001")
        
        # Let's search a few active/failed ids to offer as examples
        identity_path = os.path.join(DATA_DIR, "int_member_identity.parquet")
        if os.path.exists(identity_path):
            import secure_data
            df_identity = secure_data.read_encrypted_parquet(identity_path)
            con = duckdb.connect(database=':memory:')
            con.register("identity", df_identity)
            samples = con.execute("SELECT member_id FROM identity LIMIT 3").fetchall()
            sample_ids = [s[0] for s in samples]
            print(f"\nAvailable sample IDs to try: {', '.join(sample_ids)}")
        sys.exit(1)
        
    query_member(sys.argv[1])
