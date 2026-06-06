import os
import sys
import argparse
import joblib
import pandas as pd
import duckdb

DATA_DIR = "./data"
MODEL_PATH = "./models/churn_model_pipeline.joblib"

def score_members(top_k=None):
    # 1. Verification of files
    if not os.path.exists(MODEL_PATH):
        print(f"Error: Model pipeline file not found at {MODEL_PATH}. Please run the training notebook first.")
        sys.exit(1)
        
    features_path = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
    identity_path = os.path.join(DATA_DIR, "int_member_identity.parquet")
    if not os.path.exists(features_path):
        print(f"Error: Feature table not found at {features_path}. Run pipeline first.")
        sys.exit(1)

    print("Loading serialized model pipeline...")
    pipeline = joblib.load(MODEL_PATH)
    
    print("Loading member daily features...")
    df = pd.read_parquet(features_path)
    
    # 2. Identify the latest snapshot date to score active members
    # In our demo, this is the final date of the features table (2026-06-01)
    latest_date = df['date_day'].max()
    print(f"Scoring active members as of snapshot date: {latest_date}")
    
    active_df = df[df['date_day'] == latest_date].copy()
    print(f"Found {len(active_df):,} active members to score.")
    
    if len(active_df) == 0:
        print("No active members found on the latest date.")
        sys.exit(0)
        
    # 3. Generate Predictions
    print("Generating predictions...")
    # Get features list matching what the pipeline preprocessor expects
    categorical_cols = ['gender', 'home_studio_id', 'membership_tier']
    numeric_cols = [
        'age', 'monthly_price', 'tenure_days', 'sessions_booked_7d', 'sessions_booked_30d', 
        'sessions_attended_7d', 'sessions_attended_30d', 'attendance_rate_7d', 'attendance_rate_30d', 
        'avg_sauna_temp_30d', 'days_since_last_session', 'retail_spend_30d', 'failed_payments_count_30d', 
        'app_logins_7d', 'app_logins_30d', 'metric_views_30d', 'coach_chat_count_30d', 
        'emails_sent_30d', 'emails_opened_30d', 'emails_clicked_30d', 'email_open_rate_30d'
    ]
    boolean_cols = ['last_recurring_payment_failed', 'has_cancellation_query_30d']
    feature_cols = categorical_cols + numeric_cols + boolean_cols
    
    X = active_df[feature_cols].copy()
    probs = pipeline.predict_proba(X)[:, 1]
    
    # Save scores
    active_df['churn_probability'] = probs
    
    # Define risk tier
    def get_risk_tier(prob):
        if prob < 0.20: return "Low"
        elif prob < 0.50: return "Medium"
        elif prob < 0.85: return "High"
        else: return "Critical"
        
    active_df['risk_tier'] = active_df['churn_probability'].apply(get_risk_tier)
    active_df['score_date'] = latest_date
    
    # Write to Parquet (only de-identified)
    scorecard_df = active_df[['hashed_member_id', 'score_date', 'churn_probability', 'risk_tier']].copy()
    out_scores_path = os.path.join(DATA_DIR, "churn_scores_daily.parquet")
    scorecard_df.to_parquet(out_scores_path, index=False)
    print(f"Successfully saved {len(scorecard_df):,} de-identified scores to: {out_scores_path}")
    
    # 4. Top K report with PII and Expanations
    if top_k:
        print(f"\nFETCHING TOP {top_k} AT-RISK MEMBERS...")
        
        # Load Identity details
        if not os.path.exists(identity_path):
            print(f"Error: Secure identity path {identity_path} not found. Cannot resolve names.")
            sys.exit(1)
            
        import secure_data
        identity_df = secure_data.read_encrypted_parquet(identity_path)
        
        # Select top k
        top_at_risk = active_df.sort_values(by='churn_probability', ascending=False).head(top_k)
        
        # Join with identity details in-memory only (never saved)
        report_df = top_at_risk.merge(identity_df, on='hashed_member_id')
        
        print("\n" + "="*140)
        print(f"TOP {top_k} AT-RISK MEMBER AUDIT & EXPLANATIONS REPORT")
        print("="*140)
        
        for idx, row in report_df.iterrows():
            prob = row['churn_probability']
            tier = row['risk_tier']
            name = row['name']
            member_id = row['member_id']
            email = row['email']
            studio = row['home_studio_id']
            tier_name = row['membership_tier']
            
            # Formulate behavioral explanation based on features
            explanations = []
            if row['last_recurring_payment_failed']:
                explanations.append("Recurring membership fee payment FAILED.")
            if row['failed_payments_count_30d'] > 0:
                explanations.append(f"Had {row['failed_payments_count_30d']} failed payment events in last 30 days.")
            if row['has_cancellation_query_30d']:
                explanations.append("Inquired in AI Coach chat about freezing/cancelling account.")
            if row['days_since_last_session'] > 14:
                explanations.append(f"Inactivity: no sauna session bookings attended for {row['days_since_last_session']} days.")
            if row['sessions_attended_30d'] < 3:
                explanations.append(f"Drop-off: only {row['sessions_attended_30d']} sessions attended in the last 30 days.")
            if row['app_logins_30d'] < 4:
                explanations.append(f"Low engagement: only {row['app_logins_30d']} app logins in the last 30 days.")
            if row['sessions_booked_30d'] > 0 and row['attendance_rate_30d'] < 0.50:
                explanations.append(f"High no-show rate: booked {row['sessions_booked_30d']} classes but attended only {row['attendance_rate_30d']:.0%}.")
                
            if not explanations:
                explanations.append("General decline in email open rate and app login frequency.")
                
            reasons_str = "; ".join(explanations)
            
            print(f"{idx+1:02d}. [{tier:8s}] {name} ({member_id}) - Risk Score: {prob:.1%}")
            print(f"    Studio: {studio} | Tier: {tier_name} | Email: {email}")
            print(f"    Explanations: {reasons_str}")
            print("-" * 140)
            
        print("="*140)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score active members for churn risk.")
    parser.add_argument("--top-k", type=int, default=None, help="Display the top K at-risk members with resolved PII and explanations.")
    args = parser.parse_args()
    
    score_members(top_k=args.top_k)
