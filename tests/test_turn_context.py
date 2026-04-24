"""Unit tests for aion.shared.turn_context."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aion.shared.turn_context import (
    TurnContext,
    TurnContextStore,
    TurnSummary,
    derive_session_id,
)


# ── derive_session_id ──────────────────────────────────────────────────────


def test_derive_session_id_explicit_header_wins():
    result = derive_session_id("acme", [], explicit_id="sess-abc-123")
    assert result == "sess-abc-123"


def test_derive_session_id_explicit_header_truncated_at_64():
    long_id = "a" * 200
    result = derive_session_id("acme", [], explicit_id=long_id)
    assert result == "a" * 64


def test_derive_session_id_invalid_chars_falls_back_to_hash():
    # Path traversal attempt must be rejected
    result = derive_session_id("acme", [], explicit_id="../../etc/passwd")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_derive_session_id_fallback_is_full_64hex():
    class _Msg:
        content = "Olá, tudo bem?"
        role = "user"

    result = derive_session_id("acme", [_Msg()], explicit_id=None)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_derive_session_id_different_tenants_produce_different_ids():
    class _Msg:
        content = "Olá"
        role = "user"

    r1 = derive_session_id("tenant-a", [_Msg()], explicit_id=None)
    r2 = derive_session_id("tenant-b", [_Msg()], explicit_id=None)
    assert r1 != r2


def test_derive_session_id_empty_messages():
    result = derive_session_id("acme", [], explicit_id=None)
    assert len(result) == 64


# ── TurnContext ────────────────────────────────────────────────────────────


def _make_turn(risk: float = 0.0, complexity: float = 0.0, intent: str | None = None) -> TurnSummary:
    return TurnSummary(
        intent=intent,
        complexity=complexity,
        model_used="gpt-4o-mini",
        risk_score=risk,
        decision="continue",
        timestamp=time.time(),
    )


def test_turn_context_rolling_window_keeps_last_3():
    ctx = TurnContext(session_id="s1", tenant="acme")
    for i in range(5):
        ctx.add_turn(_make_turn(complexity=float(i)))
    assert len(ctx.turns) == 3
    complexities = [t.complexity for t in ctx.turns]
    assert complexities == [2.0, 3.0, 4.0]


def test_turn_context_max_risk_score():
    ctx = TurnContext(session_id="s1", tenant="acme")
    ctx.add_turn(_make_turn(risk=0.3))
    ctx.add_turn(_make_turn(risk=0.9))
    ctx.add_turn(_make_turn(risk=0.5))
    assert ctx.max_risk_score == pytest.approx(0.9)


def test_turn_context_max_complexity():
    ctx = TurnContext(session_id="s1", tenant="acme")
    ctx.add_turn(_make_turn(complexity=20.0))
    ctx.add_turn(_make_turn(complexity=75.0))
    assert ctx.max_complexity == pytest.approx(75.0)


def test_turn_context_last_intent_returns_most_recent():
    ctx = TurnContext(session_id="s1", tenant="acme")
    ctx.add_turn(_make_turn(intent="legal_summary"))
    ctx.add_turn(_make_turn(intent=None))
    assert ctx.last_intent == "legal_summary"


def test_turn_context_last_intent_none_when_no_turns():
    ctx = TurnContext(session_id="s1", tenant="acme")
    assert ctx.last_intent is None


# ── TurnContextStore (fail-open) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_turn_context_store_fail_open_when_no_redis():
    store = TurnContextStore()
    # No REDIS_URL set → _get_redis returns None → load returns None (not raises)
    result = await store.load("acme", "sess-xyz")
    assert result is None


@pytest.mark.asyncio
async def test_turn_context_store_fail_open_on_redis_error():
    store = TurnContextStore()
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = ConnectionError("Redis down")
    store._redis_client = mock_redis

    result = await store.load("acme", "sess-xyz")
    assert result is None


@pytest.mark.asyncio
async def test_turn_context_store_save_fail_open_on_redis_error():
    store = TurnContextStore()
    mock_redis = AsyncMock()
    mock_redis.setex.side_effect = ConnectionError("Redis down")
    store._redis_client = mock_redis

    ctx = TurnContext(session_id="s1", tenant="acme")
    # Must not raise
    await store.save("acme", ctx)
