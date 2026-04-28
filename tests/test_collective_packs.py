"""Tests for external policy pack loading in the AION Collective router."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pack_bytes(
    pack_id: str = "pack_test",
    policies: list | None = None,
    signature: str = "aabbcc",
    publisher: str = "Sentinela Editorial",
) -> bytes:
    pack = {
        "schema_version": "1.0",
        "pack_id": pack_id,
        "name": f"Test Pack {pack_id}",
        "publisher": publisher,
        "published_at": "2026-04-27T00:00:00Z",
        "policies": policies or [{"id": "pol_001", "name": "Policy One", "sectors": ["banking"]}],
        "signature": signature,
    }
    return json.dumps(pack).encode()


def _mock_redis(stored: dict | None = None):
    """Return a mock Redis client backed by an in-memory dict."""
    store = stored or {}
    rc = MagicMock()
    rc.set = AsyncMock(side_effect=lambda k, v, ex=None: store.__setitem__(k, v))
    rc.get = AsyncMock(side_effect=lambda k: store.get(k))
    rc.delete = AsyncMock(side_effect=lambda *keys: sum(1 for k in keys if store.pop(k, None) is not None))

    async def _scan_iter(match="*"):
        for k in list(store.keys()):
            import fnmatch
            if fnmatch.fnmatch(k, match.replace("*", ".*").replace(".*", "*")):
                yield k
    rc.scan_iter = _scan_iter
    return rc


# ══════════════════════════════════════════════════════════════════════════════
# TestPolicyPackRedisHelpers
# ══════════════════════════════════════════════════════════════════════════════

class TestPolicyPackRedisHelpers:
    @pytest.fixture(autouse=True)
    def _no_pack_key(self):
        with patch.dict(os.environ, {"AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY": ""}):
            yield

    def test_store_and_get_pack(self):
        import asyncio
        from aion.routers.collective import _store_pack, _get_pack

        store = {}
        rc = _mock_redis(store)

        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True):
            asyncio.run(_store_pack("pack_x", {"pack_id": "pack_x", "name": "X"}))
            result = asyncio.run(_get_pack("pack_x"))

        assert result is not None
        assert result["pack_id"] == "pack_x"

    def test_get_missing_pack_returns_none(self):
        import asyncio
        from aion.routers.collective import _get_pack

        rc = _mock_redis({})
        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True):
            result = asyncio.run(_get_pack("nonexistent"))

        assert result is None

    def test_delete_pack(self):
        import asyncio
        from aion.routers.collective import _store_pack, _delete_pack, _get_pack

        store = {}
        rc = _mock_redis(store)
        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True):
            asyncio.run(_store_pack("pack_del", {"pack_id": "pack_del"}))
            deleted = asyncio.run(_delete_pack("pack_del"))
            after = asyncio.run(_get_pack("pack_del"))

        assert deleted is True
        assert after is None

    def test_delete_nonexistent_returns_false(self):
        import asyncio
        from aion.routers.collective import _delete_pack

        rc = _mock_redis({})
        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True):
            result = asyncio.run(_delete_pack("ghost"))

        assert result is False

    def test_list_packs_returns_summaries(self):
        import asyncio
        from aion.routers.collective import _store_pack, _list_packs

        store = {}
        rc = _mock_redis(store)
        pack_data = {
            "pack_id": "pack_a",
            "name": "Pack A",
            "publisher": "Sentinela",
            "published_at": "2026-04-27",
            "policies": [{"id": "p1"}, {"id": "p2"}],
            "loaded_at": time.time(),
        }
        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True):
            asyncio.run(_store_pack("pack_a", pack_data))
            packs = asyncio.run(_list_packs())

        assert len(packs) == 1
        assert packs[0]["pack_id"] == "pack_a"
        assert packs[0]["policy_count"] == 2

    def test_no_redis_returns_empty_gracefully(self):
        import asyncio
        from aion.routers.collective import _list_packs, _get_pack_policies

        with patch("aion.middleware._redis_available", False):
            packs = asyncio.run(_list_packs())
            policies = asyncio.run(_get_pack_policies())

        assert packs == []
        assert policies == []


# ══════════════════════════════════════════════════════════════════════════════
# TestGetPackPolicies
# ══════════════════════════════════════════════════════════════════════════════

class TestGetPackPolicies:
    @pytest.fixture(autouse=True)
    def _no_pack_key(self):
        with patch.dict(os.environ, {"AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY": ""}):
            yield

    def test_pack_policies_appear_in_results(self):
        import asyncio
        from aion.routers.collective import _store_pack, _get_pack_policies

        store = {}
        rc = _mock_redis(store)
        pack_data = {
            "pack_id": "pack_banking",
            "publisher": "Sentinela Editorial",
            "published_at": "2026-04-27",
            "policies": [
                {
                    "id": "pol_pii_brazil",
                    "name": "PII Guard Brazil",
                    "sectors": ["banking"],
                    "description": "PII protection for Brazil",
                }
            ],
            "loaded_at": time.time(),
        }
        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True):
            asyncio.run(_store_pack("pack_banking", pack_data))
            policies = asyncio.run(_get_pack_policies())

        assert len(policies) == 1
        assert policies[0].id == "pol_pii_brazil"
        assert "pack_banking" in policies[0].provenance.author

    def test_malformed_policy_in_pack_is_skipped(self):
        import asyncio
        from aion.routers.collective import _store_pack, _get_pack_policies

        store = {}
        rc = _mock_redis(store)
        pack_data = {
            "pack_id": "pack_bad",
            "publisher": "X",
            "published_at": "2026-04-27",
            "policies": [
                {"id": "ok_pol", "name": "Good Policy"},
                # missing id — will fail CollectivePolicy validation
                {"name": "No ID Policy"},
            ],
            "loaded_at": time.time(),
        }
        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True):
            asyncio.run(_store_pack("pack_bad", pack_data))
            policies = asyncio.run(_get_pack_policies())

        # Only the valid one should be returned
        ids = [p.id for p in policies]
        assert "ok_pol" in ids


# ══════════════════════════════════════════════════════════════════════════════
# TestLoadPackEndpoint (unit — no full FastAPI startup)
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadPackEndpoint:
    @pytest.fixture(autouse=True)
    def _no_pack_key(self):
        with patch.dict(os.environ, {"AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY": ""}):
            yield

    def test_load_valid_pack(self):
        import asyncio
        from aion.routers.collective import load_policy_pack

        raw = _make_pack_bytes(signature="deadbeef")

        request = MagicMock()
        request.body = AsyncMock(return_value=raw)

        store = {}
        rc = _mock_redis(store)
        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True):
            result = asyncio.run(load_policy_pack(request))

        assert result["pack_id"] == "pack_test"
        assert result["status"] == "loaded"
        assert result["policy_count"] == 1

    def test_load_empty_body_raises_400(self):
        import asyncio
        from fastapi import HTTPException
        from aion.routers.collective import load_policy_pack

        request = MagicMock()
        request.body = AsyncMock(return_value=b"")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(load_policy_pack(request))

        assert exc_info.value.status_code == 400

    def test_load_pack_with_invalid_signature_raises_422(self):
        """With a real Ed25519 key configured, unsigned pack is rejected."""
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            pytest.skip("cryptography not installed")

        import asyncio
        from fastapi import HTTPException
        from aion.routers.collective import load_policy_pack

        priv = Ed25519PrivateKey.generate()
        pub_pem = priv.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()

        raw = _make_pack_bytes(signature="badbadbadbad")
        request = MagicMock()
        request.body = AsyncMock(return_value=raw)

        with patch.dict(os.environ, {"AION_TRUST_GUARD_POLICY_PACK_PUBLIC_KEY": pub_pem}), \
             pytest.raises(HTTPException) as exc_info:
            asyncio.run(load_policy_pack(request))

        assert exc_info.value.status_code == 422
        assert "signature" in exc_info.value.detail

    def test_load_and_list_packs(self):
        import asyncio
        from aion.routers.collective import load_policy_pack, list_policy_packs

        raw = _make_pack_bytes(pack_id="pack_list_test", signature="ff00ff")
        request = MagicMock()
        request.body = AsyncMock(return_value=raw)

        store = {}
        rc = _mock_redis(store)
        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True):
            asyncio.run(load_policy_pack(request))
            listing = asyncio.run(list_policy_packs())

        assert listing["count"] == 1
        assert listing["packs"][0]["pack_id"] == "pack_list_test"

    def test_remove_pack(self):
        import asyncio
        from aion.routers.collective import load_policy_pack, remove_policy_pack

        raw = _make_pack_bytes(pack_id="pack_remove", signature="cc00cc")
        request = MagicMock()
        request.body = AsyncMock(return_value=raw)

        store = {}
        rc = _mock_redis(store)
        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True):
            asyncio.run(load_policy_pack(request))
            result = asyncio.run(remove_policy_pack("pack_remove"))

        assert result["status"] == "removed"

    def test_remove_nonexistent_pack_raises_404(self):
        import asyncio
        from fastapi import HTTPException
        from aion.routers.collective import remove_policy_pack

        rc = _mock_redis({})
        with patch("aion.middleware._redis_client", rc), \
             patch("aion.middleware._redis_available", True), \
             pytest.raises(HTTPException) as exc_info:
            asyncio.run(remove_policy_pack("ghost_pack"))

        assert exc_info.value.status_code == 404
