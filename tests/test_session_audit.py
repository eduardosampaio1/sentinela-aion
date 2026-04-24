"""Unit tests for aion.shared.session_audit."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import AsyncMock, patch

import pytest

from aion.shared.session_audit import (
    SessionAuditStore,
    SessionRecord,
    TurnAuditEntry,
    _hash_message,
    get_session_audit_store,
)


def _make_entry(request_id: str = "req-001") -> TurnAuditEntry:
    return TurnAuditEntry(
        request_id=request_id,
        timestamp=time.time(),
        user_message_hash=_hash_message("Olá, qual é o status do meu contrato?"),
        decision="continue",
        model_used="gpt-4o-mini",
        risk_score=0.1,
        tokens_sent=120,
        latency_ms=95.0,
    )


# ── _hash_message ──────────────────────────────────────────────────────────


def test_hash_message_is_deterministic():
    h1 = _hash_message("same message")
    h2 = _hash_message("same message")
    assert h1 == h2


def test_hash_message_empty_returns_empty():
    assert _hash_message(None) == ""
    assert _hash_message("") == ""


def test_hash_message_is_not_reversible():
    original = "CPF: 123.456.789-00"
    h = _hash_message(original)
    assert original not in h


# ── SessionRecord — sign / verify ─────────────────────────────────────────


def test_session_record_sign_produces_hmac_with_key_id(monkeypatch):
    monkeypatch.setenv("AION_SESSION_AUDIT_SECRET", "test-secret-key")
    rec = SessionRecord(session_id="s1", tenant="acme", started_at=time.time())
    rec.turns.append(_make_entry())
    rec.sign()

    assert rec.hmac_signature != ""
    # key_id prefix format: "kid:v1:<hex>"
    assert rec.hmac_signature.startswith("kid:")


def test_session_record_verify_passes_on_untampered(monkeypatch):
    monkeypatch.setenv("AION_SESSION_AUDIT_SECRET", "test-secret-key")
    rec = SessionRecord(session_id="s1", tenant="acme", started_at=time.time())
    rec.turns.append(_make_entry())
    rec.sign()

    assert rec.verify() is True


def test_session_record_verify_fails_on_tampered_turns(monkeypatch):
    monkeypatch.setenv("AION_SESSION_AUDIT_SECRET", "test-secret-key")
    rec = SessionRecord(session_id="s1", tenant="acme", started_at=time.time())
    rec.turns.append(_make_entry())
    rec.sign()

    # Tamper: change risk_score after signing
    rec.turns[0].risk_score = 0.99
    assert rec.verify() is False


def test_session_record_verify_returns_unsigned_false_when_no_secret(monkeypatch):
    monkeypatch.delenv("AION_SESSION_AUDIT_SECRET", raising=False)
    rec = SessionRecord(session_id="s1", tenant="acme")
    rec.turns.append(_make_entry())
    rec.sign()

    # No secret → signature is empty → verify returns False (not True — unsigned != verified)
    assert rec.hmac_signature == ""
    assert rec.verify() is False


def test_session_record_sign_different_tenants_produce_different_sigs(monkeypatch):
    monkeypatch.setenv("AION_SESSION_AUDIT_SECRET", "test-secret-key")
    now = time.time()
    entry = _make_entry()

    rec_a = SessionRecord(session_id="s1", tenant="tenant-a", started_at=now)
    rec_a.turns.append(entry)
    rec_a.sign()

    rec_b = SessionRecord(session_id="s1", tenant="tenant-b", started_at=now)
    rec_b.turns.append(entry)
    rec_b.sign()

    # AAD includes tenant — same turns + different tenant = different signature
    assert rec_a.hmac_signature != rec_b.hmac_signature


# ── SessionAuditStore — fail-open ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_audit_store_fail_open_when_no_redis():
    store = SessionAuditStore()
    # No REDIS_URL → returns None without raising
    result = await store.get_session("acme", "sess-xyz")
    assert result is None


@pytest.mark.asyncio
async def test_session_audit_store_append_fail_open_on_error():
    store = SessionAuditStore()
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = ConnectionError("Redis down")
    store._redis_client = mock_redis

    entry = _make_entry()
    # Must not raise
    await store.append_turn("acme", "sess-xyz", entry)


@pytest.mark.asyncio
async def test_session_audit_store_get_session_returns_none_on_corrupt_data(caplog):
    """Corrupt Redis data must log a warning and return None, not crash."""
    import logging
    store = SessionAuditStore()
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "{ this is not valid json %%% }"
    store._redis_client = mock_redis

    with caplog.at_level(logging.WARNING, logger="aion.session_audit"):
        result = await store.get_session("acme", "sess-bad")

    assert result is None
    assert any("corrupt" in r.message.lower() or "invalid" in r.message.lower()
               for r in caplog.records)
