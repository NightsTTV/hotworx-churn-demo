import os
import time
import duckdb
import pandas as pd

# Paths
DATA_DIR = "./data"
MODELS_DIR = "./models"

def main():
    print("==================================================")
    print("STARTING PHASE 2 FEATURE ENGINEERING PIPELINE")
    print("Orchestrating DuckDB SQL models...")
    print("==================================================")
    
    start_time = time.time()
    
    # 1. Establish DuckDB connection
    con = duckdb.connect(database=':memory:')
    
    # 2. Register raw Parquet files as views
    raw_files = {
        "raw_studios": "studios.parquet",
        "raw_members": "members.parquet",
        "raw_memberships": "memberships.parquet",
        "raw_sessions": "sessions.parquet",
        "raw_transactions": "transactions.parquet",
        "raw_app_events": "app_events.parquet",
        "raw_ai_coach_chats": "ai_coach_chats.parquet",
        "raw_email_events": "email_events.parquet",
        "raw_ground_truth": "ground_truth.parquet"
    }
    
    print("\n[Step 1] Registering raw parquet files...")
    for view_name, file_name in raw_files.items():
        file_path = os.path.join(DATA_DIR, file_name)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Source file {file_path} not found. Please run generate_synthetic_data.py first.")
        con.execute(f"CREATE OR REPLACE TEMPORARY VIEW {view_name} AS SELECT * FROM read_parquet('{file_path}');")
        print(f"Registered view '{view_name}' pointing to '{file_path}'")
        
    # 3. Run Staging SQL Models
    print("\n[Step 2] Executing staging models...")
    staging_sql_files = [
        "stg_studios.sql",
        "stg_members.sql",
        "stg_memberships.sql",
        "stg_sessions.sql",
        "stg_transactions.sql",
        "stg_app_events.sql",
        "stg_ai_coach_chats.sql",
        "stg_email_events.sql",
        "stg_ground_truth.sql"
    ]
    
    for sql_file in staging_sql_files:
        model_name = sql_file.replace(".sql", "")
        file_path = os.path.join(MODELS_DIR, "staging", sql_file)
        with open(file_path, "r") as f:
            query = f.read()
        con.execute(f"CREATE OR REPLACE TEMPORARY VIEW {model_name} AS {query};")
        print(f"Created view '{model_name}' from '{file_path}'")

    # 4. Run Intermediate SQL Models (pii identity table creation)
    print("\n[Step 3] Executing intermediate models...")
    file_path = os.path.join(MODELS_DIR, "intermediate", "int_member_identity.sql")
    with open(file_path, "r") as f:
        query = f.read()
    
    # Inject dynamic salt from secure_data
    import secure_data
    salt = secure_data.get_hashing_salt()
    query = query.replace("'hotworx_secret_salt_2026'", f"'{salt}'")
    
    con.execute(f"CREATE OR REPLACE TABLE int_member_identity AS {query};")
    print(f"Created table 'int_member_identity' from '{file_path}' (dynamic salt injected)")
 
    # Save Intermediate table to encrypted Parquet at rest
    out_identity_path = os.path.join(DATA_DIR, "int_member_identity.parquet")
    df_identity = con.execute("SELECT * FROM int_member_identity").df()
    secure_data.write_encrypted_parquet(df_identity, out_identity_path)
    print(f"Saved SECURE ENCRYPTED identity mapping to: {out_identity_path}")

    # 5. Run Fact Table SQL Model
    print("\n[Step 4] Executing daily feature engineering model (fct_member_features_daily)...")
    file_path = os.path.join(MODELS_DIR, "marts", "fct_member_features_daily.sql")
    with open(file_path, "r") as f:
        query = f.read()
    con.execute(f"CREATE OR REPLACE TABLE fct_member_features_daily AS {query};")
    print(f"Created table 'fct_member_features_daily' from '{file_path}'")

    # Save Mart table to Parquet
    out_features_path = os.path.join(DATA_DIR, "fct_member_features_daily.parquet")
    con.execute(f"COPY fct_member_features_daily TO '{out_features_path}' (FORMAT PARQUET);")
    print(f"Saved de-identified feature table to: {out_features_path}")

    # 6. Run Data Quality Checks
    print("\n[Step 5] Running Data Quality Checks...")
    
    # Test A: int_member_identity primary keys checks
    print("Running Test A (int_member_identity constraints)...")
    null_keys = con.execute("SELECT COUNT(*) FROM int_member_identity WHERE member_id IS NULL OR hashed_member_id IS NULL").fetchone()[0]
    assert null_keys == 0, f"DQ Failure: Null keys found in int_member_identity ({null_keys})"
    
    dup_member_ids = con.execute("SELECT COUNT(*) FROM (SELECT member_id FROM int_member_identity GROUP BY 1 HAVING COUNT(*) > 1)").fetchone()[0]
    assert dup_member_ids == 0, f"DQ Failure: Duplicate raw member_ids found in int_member_identity ({dup_member_ids})"
    
    dup_hashed_ids = con.execute("SELECT COUNT(*) FROM (SELECT hashed_member_id FROM int_member_identity GROUP BY 1 HAVING COUNT(*) > 1)").fetchone()[0]
    assert dup_hashed_ids == 0, f"DQ Failure: Duplicate hashed_member_ids found in int_member_identity ({dup_hashed_ids})"
    print("  -> Passed all int_member_identity constraints tests.")

    # Test B: fct_member_features_daily basic nulls and boundaries checks
    print("Running Test B (fct_member_features_daily constraints)...")
    null_features = con.execute("SELECT COUNT(*) FROM fct_member_features_daily WHERE hashed_member_id IS NULL OR date_day IS NULL").fetchone()[0]
    assert null_features == 0, f"DQ Failure: Null keys/dates found in fct_member_features_daily ({null_features})"
    
    invalid_age = con.execute("SELECT COUNT(*) FROM fct_member_features_daily WHERE age < 14 OR age > 100").fetchone()[0]
    assert invalid_age == 0, f"DQ Failure: Members with invalid ages found: {invalid_age}"
    
    invalid_rates = con.execute("""
        SELECT COUNT(*) FROM fct_member_features_daily 
        WHERE attendance_rate_30d < 0.0 OR attendance_rate_30d > 1.0 
           OR attendance_rate_7d < 0.0 OR attendance_rate_7d > 1.0
           OR email_open_rate_30d < 0.0 OR email_open_rate_30d > 1.0
    """).fetchone()[0]
    assert invalid_rates == 0, f"DQ Failure: Features out of valid range (0.0 to 1.0) found: {invalid_rates}"
    
    invalid_days_since = con.execute("SELECT COUNT(*) FROM fct_member_features_daily WHERE days_since_last_session < 0").fetchone()[0]
    assert invalid_days_since == 0, f"DQ Failure: Negative days since last session: {invalid_days_since}"
    
    label_dist = con.execute("SELECT is_churned_14d, COUNT(*) FROM fct_member_features_daily GROUP BY 1").fetchall()
    print(f"  -> Label distribution (is_churned_14d): {label_dist}")
    assert len(label_dist) == 2, f"DQ Failure: Churn label is not binary. Found: {label_dist}"
    print("  -> Passed all fct_member_features_daily constraints tests.")

    # Test C: PII Concentration Leakage Protection Checks
    print("Running Test C (PII Leakage Prevention)...")
    # C1: no raw member_id / name / email / phone COLUMNS in the fact table.
    table_info = con.execute("PRAGMA table_info('fct_member_features_daily')").fetchall()
    feature_cols = [c[1] for c in table_info]
    pii_columns = {"name", "email", "phone", "phone_number", "member_id"}
    leaked_cols = [c for c in feature_cols if c.lower() in pii_columns]
    assert not leaked_cols, f"DQ Failure: PII column leakage found in fact table: {leaked_cols}"

    # C2: no PII VALUES leaked into any text column of the fact table.
    # (Replaces a previous tautological query that computed a count but never asserted on it.)
    text_cols = [c[1] for c in table_info if c[2].upper() in ("VARCHAR", "TEXT", "STRING")]
    if text_cols:
        union_vals = " UNION ALL ".join(
            f"SELECT CAST({c} AS VARCHAR) AS v FROM fct_member_features_daily" for c in text_cols
        )
        leaked_vals = con.execute(f"""
            WITH fact_vals AS ({union_vals}),
                 pii AS (
                     SELECT name AS p FROM int_member_identity
                     UNION SELECT email FROM int_member_identity
                     UNION SELECT phone FROM int_member_identity
                 )
            SELECT COUNT(*) FROM fact_vals f JOIN pii ON f.v = pii.p
        """).fetchone()[0]
        assert leaked_vals == 0, f"DQ Failure: {leaked_vals} PII value(s) leaked into fact table text columns"
    print("  -> Passed PII Leakage Protection tests (column + value level).")

    # Show some sample rows and performance details
    total_rows = con.execute("SELECT COUNT(*) FROM fct_member_features_daily").fetchone()[0]
    elapsed = time.time() - start_time
    
    print("\n--------------------------------------------------")
    print("PIPELINE EXECUTION AND DQ CHECKS COMPLETED")
    print(f"Total rows backfilled in feature table: {total_rows:,}")
    print(f"Elapsed Pipeline Time: {elapsed:.2f} seconds")
    print("--------------------------------------------------")
    print("==================================================")
    print("PHASE 2 COMPLETED SUCCESSFULLY")
    print("==================================================")

if __name__ == "__main__":
    main()
