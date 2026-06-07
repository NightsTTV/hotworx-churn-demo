import os
import io
import pandas as pd
from cryptography.fernet import Fernet

# A stable, valid 32-byte Base64 key for development fallback
DEV_FALLBACK_KEY = "kjBeSXQgvgrZA3O0OJPgJGndaq1PCo8uMWOfPzwy9fA=" # stable dev key
DEV_FALLBACK_SALT = "hotworx_default_dev_salt_2026"

def _is_production() -> bool:
    return os.getenv("HOTWORX_ENV", "dev").lower() in ("prod", "production")

def get_encryption_key() -> bytes:
    key_str = os.getenv("HOTWORX_IDENTITY_ENCRYPTION_KEY")
    if key_str:
        return key_str.encode()
    # No real key configured. Fail CLOSED in production rather than silently using the
    # committed dev key; still allow the dev/demo default locally (with a loud warning).
    if _is_production():
        raise RuntimeError(
            "HOTWORX_IDENTITY_ENCRYPTION_KEY is required when HOTWORX_ENV=production. "
            "Refusing to fall back to the committed dev key."
        )
    print("⚠️ WARNING: Using committed DEV encryption key (dev/demo only). "
          "Set HOTWORX_IDENTITY_ENCRYPTION_KEY for real data.")
    return DEV_FALLBACK_KEY.encode()

def get_hashing_salt() -> str:
    salt = os.getenv("HOTWORX_IDENTITY_SALT")
    if salt:
        return salt
    if _is_production():
        raise RuntimeError(
            "HOTWORX_IDENTITY_SALT is required when HOTWORX_ENV=production. "
            "Refusing to fall back to the committed dev salt."
        )
    return DEV_FALLBACK_SALT

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
