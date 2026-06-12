"""
Phase 4 — Verification & Edge Cases for the AI Member Summary engine.

Fully OFFLINE: the LLM is mocked (no Ollama required), and the summary cache is redirected
to a temp file so runs never pollute the real encrypted cache.

Covers the three plan profiles plus the safety guarantees:
  1. High-risk member: failed billing + cancellation query in chat.
  2. Low-risk, highly engaged member.
  3. Lapsed member: inactive, NO chat records.
  - Anti-hallucination: invented numbers are rejected; payload numbers and correct
    percent-forms of probabilities are allowed.
  - Degradation chain: bad JSON -> rules; connection error -> rules; valid -> llm; repeat -> cache.
  - Payload builder (real data, if present): correct keys, NO PII fields.

Run:  .venv/bin/python test_ai_summary.py        (also pytest-compatible)
"""

import os
import json
import tempfile
from unittest.mock import patch, MagicMock

import ai_summary_engine as ase

# Redirect the encrypted cache to a temp file for the whole test run.
ase.SUMMARY_CACHE_PATH = os.path.join(tempfile.gettempdir(), "test_ai_summary_cache.parquet")


# ==============================================================================
# SIMULATED PROFILES (the three cases from the plan)
# ==============================================================================
def profile_high_risk() -> dict:
    return {
        "as_of_date": "2026-05-31", "member_ref": "TEST_HI", "membership_tier": "Premium",
        "monthly_price": 129.0, "tenure_days": 36, "churn_risk_tier": "Critical",
        "churn_probability": 0.973, "lifecycle_stage": "at_risk", "days_in_stage": 2,
        "days_since_last_session": 16, "sessions_attended_30d": 2, "sessions_booked_30d": 4,
        "attendance_rate_30d": 0.5, "app_logins_30d": 3, "coach_chats_30d": 2,
        "retail_spend_30d": 0.0, "email_open_rate_30d": 0.25,
        "recent_payment_failed": True, "failed_payments_30d": 1,
        "has_cancellation_query_30d": True,
        "recent_chat_messages": [
            {"timestamp": "2026-05-20T10:24:00", "sender": "member",
             "text": "Why was my card declined? Also how do I cancel my subscription right now?"},
        ],
    }


def profile_low_risk() -> dict:
    return {
        "as_of_date": "2026-05-31", "member_ref": "TEST_LO", "membership_tier": "VIP",
        "monthly_price": 99.0, "tenure_days": 412, "churn_risk_tier": "Low",
        "churn_probability": 0.012, "lifecycle_stage": "engaged", "days_in_stage": 300,
        "days_since_last_session": 1, "sessions_attended_30d": 14, "sessions_booked_30d": 15,
        "attendance_rate_30d": 0.93, "app_logins_30d": 22, "coach_chats_30d": 1,
        "retail_spend_30d": 45.0, "email_open_rate_30d": 0.8,
        "recent_payment_failed": False, "failed_payments_30d": 0,
        "has_cancellation_query_30d": False,
        "recent_chat_messages": [
            {"timestamp": "2026-05-18T08:00:00", "sender": "member",
             "text": "How do I build core strength faster?"},
        ],
    }


def profile_lapsed_no_chats() -> dict:
    return {
        "as_of_date": "2026-05-31", "member_ref": "TEST_LA", "membership_tier": "Basic",
        "monthly_price": 59.0, "tenure_days": 220, "churn_risk_tier": "High",
        "churn_probability": 0.61, "lifecycle_stage": "lapsed", "days_in_stage": 18,
        "days_since_last_session": 41, "sessions_attended_30d": 0, "sessions_booked_30d": 0,
        "attendance_rate_30d": None, "app_logins_30d": 0, "coach_chats_30d": 0,
        "retail_spend_30d": 0.0, "email_open_rate_30d": 0.0,
        "recent_payment_failed": False, "failed_payments_30d": 0,
        "has_cancellation_query_30d": False,
        "recent_chat_messages": [],  # the no-chat edge case
    }


def _mock_response(content: str):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    return r


GOOD_LLM_JSON = json.dumps({
    "summary": "This member's payment failed recently and they asked about cancelling; attendance has dropped sharply.",
    "next_steps": ["Call to resolve the billing issue.", "Address the cancellation question directly."],
    "talking_points": ["Lead with helping, not selling."],
})


# ==============================================================================
# TESTS
# ==============================================================================
def test_rules_summary_high_risk():
    out = ase.rules_based_summary(profile_high_risk())
    text = out["summary"].lower() + " " + " ".join(out["next_steps"]).lower()
    assert "payment" in text, "must surface the failed payment"
    assert "cancel" in text, "must surface the cancellation query"
    assert "16" in out["summary"], "must surface inactivity days"
    assert out["source"] == "rules"


def test_rules_summary_low_risk():
    out = ase.rules_based_summary(profile_low_risk())
    joined = (out["summary"] + " ".join(out["next_steps"])).lower()
    assert "payment" not in joined and "cancel" not in joined
    assert out["next_steps"], "still provides a friendly check-in step"


def test_rules_summary_lapsed_no_chats():
    out = ase.rules_based_summary(profile_lapsed_no_chats())
    assert "41" in out["summary"], "must surface 41 days inactive"
    assert out["next_steps"] and out["talking_points"]


def test_validator_rejects_invented_numbers():
    p = profile_high_risk()
    assert not ase._validate_no_invented_numbers("Offer them a $150 credit over 60 days.", p)
    assert ase._validate_no_invented_numbers("They pay $129 monthly and have been inactive 16 days.", p)
    # Correct percent form of churn_probability 0.973 must be allowed:
    assert ase._validate_no_invented_numbers("Churn risk is about 97.3% right now.", p)
    # Single digits (suggestions like 'try 2 sessions a week') are allowed:
    assert ase._validate_no_invented_numbers("Try 2 sessions a week.", p)


def test_extract_json_tolerates_fences_and_garbage():
    obj = {"summary": "s", "next_steps": ["a"]}
    assert ase._extract_json(json.dumps(obj)) == obj
    assert ase._extract_json("```json\n" + json.dumps(obj) + "\n```") == obj
    assert ase._extract_json("total nonsense, no braces") is None


def test_synthesis_good_output_then_cache():
    if os.path.exists(ase.SUMMARY_CACHE_PATH):
        os.remove(ase.SUMMARY_CACHE_PATH)
    p = profile_high_risk()
    with patch("requests.post", return_value=_mock_response(GOOD_LLM_JSON)) as mock_post:
        out = ase.synthesize_summary(p, force_refresh=True)
        assert out["source"] == "llm", out
        assert mock_post.called
    # Second call: served from encrypted cache, no HTTP at all.
    with patch("requests.post", side_effect=AssertionError("must not be called")):
        out2 = ase.synthesize_summary(p)
        assert out2["source"] == "cache"


def test_synthesis_rejects_hallucinated_numbers():
    bad = json.dumps({
        "summary": "They have missed 27 sessions and owe $450.",  # invented figures
        "next_steps": ["Call them."], "talking_points": ["Hi!"],
    })
    with patch("requests.post", return_value=_mock_response(bad)):
        out = ase.synthesize_summary(profile_low_risk(), force_refresh=True)
    assert out["source"] == "rules"
    assert "numbers" in out["fallback_reason"]


def test_synthesis_unparseable_falls_back():
    with patch("requests.post", return_value=_mock_response("I think this member is great!")):
        out = ase.synthesize_summary(profile_lapsed_no_chats(), force_refresh=True)
    assert out["source"] == "rules"
    assert "unparseable" in out["fallback_reason"]


def test_synthesis_server_down_falls_back():
    import requests as _r
    with patch("requests.post", side_effect=_r.exceptions.ConnectionError("refused")):
        out = ase.synthesize_summary(profile_high_risk(), force_refresh=True)
    assert out["source"] == "rules"
    assert "unavailable" in out["fallback_reason"]


def test_prompt_guards_present():
    sp = ase.SYSTEM_PROMPT
    assert "Never invent numbers" in sp
    assert "NEVER as instructions" in sp, "prompt-injection guard missing"
    assert "JSON" in sp


def test_real_payload_has_no_pii():
    """If the real warehouse is present, the payload must carry the right keys and ZERO PII."""
    if not os.path.exists(ase.FEATURES_PATH):
        print("  (skipped — no local data)")
        return
    import duckdb
    hid = duckdb.connect().execute(
        f"""SELECT hashed_member_id FROM read_parquet('{ase.FEATURES_PATH}')
            WHERE date_day = (SELECT MAX(date_day) FROM read_parquet('{ase.FEATURES_PATH}')) LIMIT 1"""
    ).fetchone()[0]
    p = ase.build_member_payload(hid)
    assert p is not None
    for k in ("as_of_date", "membership_tier", "days_since_last_session",
              "recent_payment_failed", "has_cancellation_query_30d", "recent_chat_messages"):
        assert k in p, f"missing key {k}"
    for pii in ("name", "email", "phone"):
        assert pii not in p, f"PII field '{pii}' leaked into payload"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print("-" * 50)
    print(f"{len(tests) - failed}/{len(tests)} tests passed")
    raise SystemExit(1 if failed else 0)
