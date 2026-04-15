"""Tests for X-Idempotency-Key cache replay across integration modes."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from aion import config as cfg
    cfg._settings = None
    os.environ.setdefault("OPENAI_API_KEY", "sk-test")
    from aion.main import app
    with TestClient(app) as c:
        yield c


def _greeting() -> dict:
    return {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "oi"}]}


def _key() -> str:
    return f"idk_{uuid.uuid4().hex[:12]}"


# ── IdempotencyCache (unit) ──

class TestIdempotencyCache:
    @pytest.mark.asyncio
    async def test_miss_returns_none(self):
        from aion.contract import get_idempotency_cache
        cache = get_idempotency_cache()
        result = await cache.get("test-tenant", "missing_key_xyz")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_then_get(self):
        from aion.contract import (
            Action,
            ContractMeta,
            DecisionContract,
            FinalOutput,
            get_idempotency_cache,
        )
        contract = DecisionContract(
            request_id="req_test",
            action=Action.BYPASS,
            final_output=FinalOutput(target_type="direct", payload={"response": None}),
            meta=ContractMeta(tenant="test-tenant", timestamp=0.0),
        )
        cache = get_idempotency_cache()
        await cache.set("test-tenant", "my_key_1", contract, response={"foo": 1}, executed=True)

        cached = await cache.get("test-tenant", "my_key_1")
        assert cached is not None
        assert cached.contract.request_id == "req_test"
        assert cached.response == {"foo": 1}
        assert cached.executed is True
        assert cached.side_effects_possible is False  # BYPASS = none


# ── End-to-end replay ──

class TestTransparentReplay:
    def test_same_key_returns_same_response(self, client: TestClient):
        key = _key()
        r1 = client.post("/v1/chat/completions", json=_greeting(), headers={"X-Idempotency-Key": key})
        r2 = client.post("/v1/chat/completions", json=_greeting(), headers={"X-Idempotency-Key": key})
        assert r1.status_code == 200
        assert r2.status_code == 200
        # Body identical
        assert r1.json() == r2.json()
        # Second hit is cached
        assert r2.headers.get("X-Aion-Idempotent-Hit") == "true"
        assert r1.headers.get("X-Aion-Idempotent-Hit") != "true"

    def test_different_keys_are_independent(self, client: TestClient):
        r1 = client.post("/v1/chat/completions", json=_greeting(), headers={"X-Idempotency-Key": _key()})
        r2 = client.post("/v1/chat/completions", json=_greeting(), headers={"X-Idempotency-Key": _key()})
        assert r1.headers.get("X-Aion-Idempotent-Hit") != "true"
        assert r2.headers.get("X-Aion-Idempotent-Hit") != "true"

    def test_no_key_disables_cache(self, client: TestClient):
        r1 = client.post("/v1/chat/completions", json=_greeting())
        r2 = client.post("/v1/chat/completions", json=_greeting())
        assert r1.headers.get("X-Aion-Idempotent-Hit") != "true"
        assert r2.headers.get("X-Aion-Idempotent-Hit") != "true"


class TestAssistedReplay:
    def test_same_key_returns_same_contract(self, client: TestClient):
        key = _key()
        r1 = client.post("/v1/chat/assisted", json=_greeting(), headers={"X-Idempotency-Key": key})
        r2 = client.post("/v1/chat/assisted", json=_greeting(), headers={"X-Idempotency-Key": key})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.headers.get("X-Aion-Idempotent-Hit") == "true"
        # Contract request_id stays the same on replay
        assert r1.json()["contract"]["request_id"] == r2.json()["contract"]["request_id"]


class TestDecisionReplay:
    def test_same_key_returns_same_contract(self, client: TestClient):
        key = _key()
        r1 = client.post("/v1/decisions", json=_greeting(), headers={"X-Idempotency-Key": key})
        r2 = client.post("/v1/decisions", json=_greeting(), headers={"X-Idempotency-Key": key})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.headers.get("X-Aion-Idempotent-Hit") == "true"
        assert r1.json()["request_id"] == r2.json()["request_id"]
