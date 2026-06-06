import os
import io
import pandas as pd
from cryptography.fernet import Fernet

# A stable, valid 32-byte Base64 key for development fallback
DEV_FALLBACK_KEY = "kjBeSXQgvgrZA3O0OJPgJGndaq1PCo8uMWOfPzwy9fA=" # stable dev key
DEV_FALLBACK_SALT = "hotworx_default_dev_salt_2026"

def get_encryption_key() -> bytes:
    key_str = os.getenv("HOTWORX_IDENTITY_ENCRYPTION_KEY")
    if not key_str:
        print("⚠️ WARNING: Using fallback development encryption key. Do not run in production!")
        key_str = DEV_FALLBACK_KEY
    return key_str.encode()

def get_hashing_salt() -> str:
    salt = os.getenv("HOTWORX_IDENTITY_SALT")
    if not salt:
        salt = DEV_FALLBACK_SALT
    return salt

def encrypt_dataframe(df: pd.DataFrame) -> bytes:
    key = get_encryption_key()
    fernet = Fernet(key)
    # Serialize to Parquet format in-memory
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    raw_bytes = buffer.getvalue()
    return fernet.encrypt(raw_bytes)

def decrypt_dataframe(encrypted_bytes: bytes) -> pd.DataFrame:
    key = get_encryption_key()
    fernet = Fernet(key)
    decrypted_bytes = fernet.decrypt(encrypted_bytes)
    return pd.read_parquet(io.BytesIO(decrypted_bytes))

def write_encrypted_parquet(df: pd.DataFrame, filepath: str):
    encrypted_bytes = encrypt_dataframe(df)
    with open(filepath, "wb") as f:
        f.write(encrypted_bytes)

def read_encrypted_parquet(filepath: str) -> pd.DataFrame:
    with open(filepath, "rb") as f:
        encrypted_bytes = f.read()
    return decrypt_dataframe(encrypted_bytes)
