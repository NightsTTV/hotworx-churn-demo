import os
import sys
import hashlib
import pandas as pd
import secure_data

DATA_DIR = "./data"

def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Pure Python Jaro-Winkler string similarity calculation."""
    s1 = "".join(s1.lower().split())
    s2 = "".join(s2.lower().split())
    
    if s1 == s2:
        return 1.0
        
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0
        
    max_dist = max(len1, len2) // 2 - 1
    s1_matches = [False] * len1
    s2_matches = [False] * len2
    
    matches = 0
    for i in range(len1):
        start = max(0, i - max_dist)
        end = min(len2, i + max_dist + 1)
        for j in range(start, end):
            if not s2_matches[j] and s1[i] == s2[j]:
                s1_matches[i] = True
                s2_matches[j] = True
                matches += 1
                break
                
    if matches == 0:
        return 0.0
        
    transpositions = 0
    k = 0
    for i in range(len1):
        if s1_matches[i]:
            while not s2_matches[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1
            
    transpositions //= 2
    jaro = (matches / len1 + matches / len2 + (matches - transpositions) / matches) / 3.0
    
    prefix = 0
    for i in range(min(4, min(len1, len2))):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break
            
    return jaro + prefix * 0.1 * (1.0 - jaro)

# ==============================================================================
# FIELD NORMALIZATION
# ==============================================================================
def normalize_email(email: str) -> str:
    if not isinstance(email, str):
        return ""
    return email.strip().lower()

def normalize_phone(phone: str) -> str:
    if not isinstance(phone, str):
        return ""
    # Retain only digits
    digits = "".join(c for c in phone if c.isdigit())
    # Strip leading country code if 11 digits starting with 1 (standard US)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits

def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = name.strip().lower()
    # Remove punctuation/special characters
    name = "".join(c for c in name if c.isalnum() or c.isspace())
    return name

# ==============================================================================
# RESOLVER ENGINE
# ==============================================================================
def resolve_identities(pos_df: pd.DataFrame, app_df: pd.DataFrame) -> pd.DataFrame:
    """Fuzzy joins multi-source POS and App records into a unified identity log."""
    print("Normalizing records for matching...")
    
    pos_df = pos_df.copy()
    app_df = app_df.copy()
    
    # Apply normalizations
    pos_df["norm_email"] = pos_df["email"].apply(normalize_email)
    pos_df["norm_phone"] = pos_df["phone"].apply(normalize_phone)
    pos_df["norm_name"] = pos_df["name"].apply(normalize_name)
    
    app_df["norm_email"] = app_df["email"].apply(normalize_email)
    app_df["norm_phone"] = app_df["phone"].apply(normalize_phone)
    app_df["norm_name"] = app_df["name"].apply(normalize_name)
    
    # Hashing pepper from secure_data config
    salt = secure_data.get_hashing_salt()
    
    resolved_records = []
    app_matched = set()
    
    print("Executing matching layers...")
    for p_idx, pos_row in pos_df.iterrows():
        p_email = pos_row["norm_email"]
        p_phone = pos_row["norm_phone"]
        p_name = pos_row["norm_name"]
        
        match_row = None
        
        # Layer 1: Exact Email match
        if p_email:
            email_matches = app_df[(app_df["norm_email"] == p_email) & (~app_df["app_member_id"].isin(app_matched))]
            if not email_matches.empty:
                match_row = email_matches.iloc[0]
                
        # Layer 2: Exact Phone match
        if match_row is None and p_phone:
            phone_matches = app_df[(app_df["norm_phone"] == p_phone) & (~app_df["app_member_id"].isin(app_matched))]
            if not phone_matches.empty:
                match_row = phone_matches.iloc[0]
                
        # Layer 3: Fuzzy Name match with partially matching contact coordinates
        if match_row is None:
            # Look for candidates with same email domain or same phone area code, then verify fuzzy name
            potential_candidates = app_df[~app_df["app_member_id"].isin(app_matched)]
            for c_idx, candidate in potential_candidates.iterrows():
                # Check Jaro-Winkler
                name_sim = jaro_winkler_similarity(p_name, candidate["norm_name"])
                # If name is highly similar and email or phone has overlap
                if name_sim >= 0.85:
                    if (p_email and candidate["norm_email"] and p_email.split("@")[0] == candidate["norm_email"].split("@")[0]) or \
                       (p_phone and candidate["norm_phone"] and p_phone[:3] == candidate["norm_phone"][:3]):
                        match_row = candidate
                        break
                        
        # Save mapping
        if match_row is not None:
            app_matched.add(match_row["app_member_id"])
            # Generate stable surrogate key based on normalized email (primary pos email)
            hashed_id = hashlib.sha256(f"{p_email}{salt}".encode("utf-8")).hexdigest()
            resolved_records.append({
                "member_id": pos_row["member_id"],
                "app_member_id": match_row["app_member_id"],
                "hashed_member_id": hashed_id,
                "name": pos_row["name"], # POS preferred name
                "email": pos_row["email"],
                "phone": pos_row["phone"]
            })
        else:
            # Isolated POS member (no app registration found)
            hashed_id = hashlib.sha256(f"{p_email}{salt}".encode("utf-8")).hexdigest()
            resolved_records.append({
                "member_id": pos_row["member_id"],
                "app_member_id": "NONE",
                "hashed_member_id": hashed_id,
                "name": pos_row["name"],
                "email": pos_row["email"],
                "phone": pos_row["phone"]
            })
            
    # Also add remaining app members that had no matching POS records
    for _, app_row in app_df[~app_df["app_member_id"].isin(app_matched)].iterrows():
        a_email = app_row["norm_email"]
        hashed_id = hashlib.sha256(f"{a_email}{salt}".encode("utf-8")).hexdigest()
        resolved_records.append({
            "member_id": "NONE",
            "app_member_id": app_row["app_member_id"],
            "hashed_member_id": hashed_id,
            "name": app_row["name"],
            "email": app_row["email"],
            "phone": app_row["phone"]
        })
        
    return pd.DataFrame(resolved_records)

# ==============================================================================
# MAIN TEST & DEMO SIMULATOR
# ==============================================================================
def main():
    print("="*60)
    print("RUNNING IDENTITY RESOLUTION DEMO SIMULATOR")
    print("="*60)
    
    # We will load the current decrypted identity file to simulate raw mismatched POS/App inputs
    identity_path = os.path.join(DATA_DIR, "int_member_identity.parquet")
    if not os.path.exists(identity_path):
        print(f"Error: Base identity parquet not found at {identity_path}. Run pipeline first.")
        sys.exit(1)
        
    df_raw = secure_data.read_encrypted_parquet(identity_path)
    
    # Simulate mismatched POS export
    pos_data = df_raw.head(10).copy()
    # Change formats
    pos_data["phone"] = pos_data["phone"].apply(lambda p: f"+1 {p}")
    
    # Simulate mismatched App database export (introduce slight name typo and phone difference)
    app_data = df_raw.head(10).copy()
    app_data["app_member_id"] = app_data["member_id"].apply(lambda m: f"APP_{m}")
    app_data["phone"] = app_data["phone"].apply(lambda p: p.replace("-", ""))
    
    # Let's introduce a name typo in row 1
    app_data.loc[0, "name"] = app_data.loc[0, "name"] + " Jr."
    # Let's introduce a name change/typo in row 2
    app_data.loc[1, "name"] = app_data.loc[1, "name"].replace(" ", " X. ")
    
    print(f"Noisy inputs prepared. Matching {len(pos_data)} POS rows to {len(app_data)} App rows.")
    
    resolved = resolve_identities(pos_data, app_data)
    
    print("\nResolution mapping sample:")
    print(resolved.head(3).to_string(index=False))
    print("\n✓ Fuzzy mapping run completed successfully!")

if __name__ == "__main__":
    main()
