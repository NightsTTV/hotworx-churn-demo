"""Dependency-free auth helpers for the demo dashboard.

Keeps plaintext passwords OUT of source: passwords are stored/compared as PBKDF2-HMAC-SHA256
hashes (Python stdlib) with a per-user random salt and constant-time comparison.

For production, prefer a vetted KDF (argon2/bcrypt/scrypt) and, better still, an external identity
provider (SSO/OIDC) rather than a local user table.
"""
import os
import hmac
import json
import hashlib

PBKDF2_ITERATIONS = 240_000
USERS_FILE = os.path.join(os.path.dirname(__file__), "dashboard_users.json")


def hash_password(password, salt=None):
    """Return a 'salt_hex$hash_hex' record for the given password."""
    if salt is None:
        salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"{salt}${dk.hex()}"


def verify_password(password, stored):
    """Constant-time verification of a password against a 'salt$hash' record."""
    try:
        salt, _ = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def load_user_accounts():
    """Load dashboard accounts WITHOUT plaintext passwords baked into source.

    Resolution order:
      1. dashboard_users.json   (gitignored file of {username: {password_hash, role, studio}})
      2. DASHBOARD_USERS_JSON   (the same JSON, supplied via environment / secrets manager)
      3. demo fallback          (no file present): build accounts in-memory, hashing passwords
                                taken from DASHBOARD_ADMIN_PW / DASHBOARD_GM_PW (demo defaults).
                                The plaintext is hashed immediately and never stored or logged.
    """
    raw = None
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            raw = json.load(f)
    elif os.getenv("DASHBOARD_USERS_JSON"):
        raw = json.loads(os.getenv("DASHBOARD_USERS_JSON"))

    if raw:
        return raw  # already-hashed records

    # Demo fallback: env-overridable defaults, hashed in memory.
    admin_pw = os.getenv("DASHBOARD_ADMIN_PW", "admin123")
    gm_pw = os.getenv("DASHBOARD_GM_PW", "gm123")
    accounts = {"admin": {"password_hash": hash_password(admin_pw), "role": "Admin", "studio": None}}
    for i in range(1, 11):
        accounts[f"gm_s{i:02d}"] = {"password_hash": hash_password(gm_pw), "role": "GM", "studio": f"S{i:02d}"}
    return accounts
