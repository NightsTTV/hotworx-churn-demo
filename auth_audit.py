"""
Authentication audit log + lockout  (SOC finding #1).

Turns the login from an UNLOGGED, UNTHROTTLED surface into a detectable, rate-limited one.

- Every attempt (success / failure / lockout) is appended to a HASH-CHAINED JSONL log
  (data/auth_audit.log). Each record carries the sha256 of the previous record, so deletion
  or edits are detectable via verify_chain() — local tampering no longer goes unnoticed
  (ATT&CK T1070.004 Indicator Removal, T1565 Data Manipulation). Records are flat JSON for
  trivial SIEM ingestion. The password is NEVER logged.
- Lockout: >= MAX_FAILURES within FAILURE_WINDOW (keyed on username, and on source IP when
  known) triggers a LOCKOUT backoff — throttling brute force / password spraying (T1110).

This module is intentionally Streamlit-free (pure + unit-testable). Production: ship the log
off-box (append-only object storage / SIEM) and front the app with a reverse proxy so
X-Forwarded-For is reliably populated.
"""
import os
import json
import hashlib
import datetime

DATA_DIR = "./data"
AUTH_LOG_PATH = os.path.join(DATA_DIR, "auth_audit.log")
GENESIS_HASH = "0" * 64

# Tunable policy (env-overridable).
MAX_FAILURES = int(os.getenv("AUTH_MAX_FAILURES", "5"))
FAILURE_WINDOW_MIN = int(os.getenv("AUTH_FAILURE_WINDOW_MIN", "15"))
LOCKOUT_MIN = int(os.getenv("AUTH_LOCKOUT_MIN", "15"))


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_ts(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s)


def _record_hash(prev_hash: str, record_without_hash: dict) -> str:
    payload = prev_hash + json.dumps(record_without_hash, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _last_hash() -> str:
    if not os.path.exists(AUTH_LOG_PATH):
        return GENESIS_HASH
    last = GENESIS_HASH
    with open(AUTH_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    last = json.loads(line)["hash"]
                except (json.JSONDecodeError, KeyError):
                    pass
    return last


def log_auth_event(username: str, outcome: str, source: str = "unknown", reason: str = "") -> dict:
    """Append one auth event. outcome in {success, failure, lockout}. Never logs the password."""
    os.makedirs(DATA_DIR, exist_ok=True)
    rec = {
        "ts": _utcnow().isoformat(),
        "event": "auth",
        "username": (username or "")[:64],
        "outcome": outcome,
        "source": source or "unknown",
        "reason": reason,
    }
    prev = _last_hash()
    rec["prev_hash"] = prev
    rec["hash"] = _record_hash(prev, rec)  # rec has no "hash" key yet
    with open(AUTH_LOG_PATH, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def _recent_events(within_min: int) -> list:
    if not os.path.exists(AUTH_LOG_PATH):
        return []
    cutoff = _utcnow() - datetime.timedelta(minutes=within_min)
    out = []
    with open(AUTH_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if _parse_ts(rec["ts"]) >= cutoff:
                    out.append(rec)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return out


def _failures_since_last_success(events: list, key: str, value: str) -> list:
    """Failure timestamps for events[key]==value, resetting whenever a success appears."""
    rel = sorted((e for e in events if e.get(key) == value), key=lambda e: e["ts"])
    fails = []
    for e in rel:
        if e["outcome"] == "success":
            fails = []
        elif e["outcome"] == "failure":
            fails.append(_parse_ts(e["ts"]))
    return fails


def check_lockout(username: str, source: str = "unknown") -> tuple:
    """Return (locked: bool, seconds_remaining: int).

    Locked if >= MAX_FAILURES failures within FAILURE_WINDOW_MIN (since the last success) for
    this username OR this source. Source-based lockout is SKIPPED when source is 'unknown' so a
    proxy-less deploy can't lock every user into one bucket (and to avoid a trivial all-user DoS)."""
    events = _recent_events(FAILURE_WINDOW_MIN)
    now = _utcnow()
    keys = [("username", (username or "").strip().lower())]
    if source and source != "unknown":
        keys.append(("source", source))

    locked_until = None
    for key, val in keys:
        recent = [t for t in _failures_since_last_success(events, key, val)
                  if (now - t).total_seconds() <= FAILURE_WINDOW_MIN * 60]
        if len(recent) >= MAX_FAILURES:
            until = max(recent) + datetime.timedelta(minutes=LOCKOUT_MIN)
            if locked_until is None or until > locked_until:
                locked_until = until

    if locked_until and locked_until > now:
        return True, int((locked_until - now).total_seconds())
    return False, 0


def verify_chain() -> tuple:
    """Recompute the hash chain. Returns (ok, first_broken_line or None, total_records).
    A broken/missing link means the log was edited or had records deleted."""
    if not os.path.exists(AUTH_LOG_PATH):
        return True, None, 0
    prev = GENESIS_HASH
    n = 0
    with open(AUTH_LOG_PATH) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                return False, i, n
            stored = rec.pop("hash", None)
            if rec.get("prev_hash") != prev or _record_hash(prev, rec) != stored:
                return False, i, n
            prev = stored
    return True, None, n


def main():
    """SOC utility: verify integrity + summarize recent auth activity (spray detection)."""
    print("=" * 60)
    print("AUTH AUDIT — integrity + recent activity")
    print("=" * 60)
    ok, broken, total = verify_chain()
    print(f"Hash chain: {'INTACT ✓' if ok else f'BROKEN at line {broken} ✗ (tampering/deletion)'}  ({total} records)")

    events = _recent_events(60)
    fails = [e for e in events if e["outcome"] == "failure"]
    print(f"\nLast 60 min: {len(events)} events, {len(fails)} failures")
    from collections import Counter
    if fails:
        print("  Failures by username:", dict(Counter(e["username"] for e in fails)))
        print("  Failures by source  :", dict(Counter(e["source"] for e in fails)))
        print("  -> spray indicator: many usernames from one source, or many failures on one username")
    for e in events[-10:]:
        print(f"  {e['ts']}  {e['outcome']:8s}  user={e['username']:10s}  src={e['source']}  {e.get('reason','')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
