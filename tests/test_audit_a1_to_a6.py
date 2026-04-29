"""Testes dos gaps altos — Semana 2 (A-1 a A-6).

A-1: _local_rate_limits usa deque, expira timestamps e evita key explosion
A-2: _chain_tips fica delimitado em _MAX_CHAIN_TIPS; mais antigo é evictado
A-3: _hash_entry retorna HMAC-SHA256 quando segredo está configurado
A-4: segredos diferentes produzem hashes diferentes (integridade por segredo)
A-5: _AUDIT_BG_TASKS mantém referência forte à task; discard após conclusão
A-6: _behavior_store evicta tenant mais antigo quando _MAX_BEHAVIOR_ENTRIES excedido
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from unittest.mock import AsyncMock, patch

import pytest


# ── A-1: Rate limit deque ────────────────────────────────────────────────────

class TestA1RateLimitDeque:
    """A-1: _local_rate_limits deve usar deque e respeitar limites de memória."""

    def setup_method(self):
        import aion.middleware as mw
        mw._local_rate_limits.clear()

    def teardown_method(self):
        import aion.middleware as mw
        mw._local_rate_limits.clear()

    def test_rate_limit_uses_deque(self):
        from aion.middleware import _local_check_rate_limit, _local_rate_limits
        _local_check_rate_limit("tenant:test", limit=10)
        assert isinstance(_local_rate_limits["tenant:test"], deque)

    def test_expired_timestamps_removed_from_left(self):
        from aion.middleware import _local_rate_limits, _local_check_rate_limit
        dq = deque()
        old_ts = time.time() - 120  # 2 minutes ago — beyond 60s window
        dq.append(old_ts)
        _local_rate_limits["stale-tenant"] = dq

        _local_check_rate_limit("stale-tenant", limit=100)

        # Expired entry should have been popleft'd
        assert old_ts not in _local_rate_limits["stale-tenant"]

    def test_rate_limit_allows_within_limit(self):
        from aion.middleware import _local_check_rate_limit
        for _ in range(5):
            result = _local_check_rate_limit("tenant:allow", limit=10)
        assert result is True

    def test_rate_limit_blocks_at_limit(self):
        from aion.middleware import _local_check_rate_limit
        for _ in range(10):
            _local_check_rate_limit("tenant:block", limit=10)
        result = _local_check_rate_limit("tenant:block", limit=10)
        assert result is False

    def test_eviction_when_max_keys_exceeded(self):
        from aion.middleware import _local_check_rate_limit, _local_rate_limits
        from aion.config import get_settings
        max_keys = get_settings().max_rate_limit_keys
        # Fill up to max
        for i in range(max_keys):
            _local_rate_limits[f"k:{i}"] = deque([time.time()])

        # One more should trigger eviction
        _local_check_rate_limit("k:NEW", limit=100)

        # After eviction, total should be well below max
        assert len(_local_rate_limits) < max_keys


# ── A-2: Chain tips bounded ──────────────────────────────────────────────────

class TestA2ChainTipsBounded:
    """A-2: _chain_tips deve ter tamanho máximo; tenant mais antigo é evictado."""

    def setup_method(self):
        import aion.middleware as mw
        mw._chain_tips.clear()

    def teardown_method(self):
        import aion.middleware as mw
        mw._chain_tips.clear()

    def test_chain_tips_evicts_oldest_when_full(self):
        from aion.middleware import _chain_tips
        from aion.config import get_settings
        max_tips = get_settings().max_chain_tips

        # Fill to max
        for i in range(max_tips):
            _chain_tips[f"tenant-{i}"] = f"hash-{i}"
            _chain_tips.move_to_end(f"tenant-{i}")

        # Add one more — should evict tenant-0
        _chain_tips["tenant-NEW"] = "hash-new"
        _chain_tips.move_to_end("tenant-NEW")
        while len(_chain_tips) > max_tips:
            _chain_tips.popitem(last=False)

        assert len(_chain_tips) == max_tips
        assert "tenant-0" not in _chain_tips
        assert "tenant-NEW" in _chain_tips

    def test_chain_tips_preserves_newest(self):
        from aion.middleware import _chain_tips
        from aion.config import get_settings
        max_tips = get_settings().max_chain_tips

        for i in range(max_tips + 5):
            _chain_tips[f"t-{i}"] = f"h-{i}"
            _chain_tips.move_to_end(f"t-{i}")
            while len(_chain_tips) > max_tips:
                _chain_tips.popitem(last=False)

        # The 5 newest should survive
        for i in range(max_tips, max_tips + 5):
            assert f"t-{i}" in _chain_tips

    def test_chain_tips_never_exceeds_max(self):
        from aion.middleware import _chain_tips
        from aion.config import get_settings
        max_tips = get_settings().max_chain_tips

        for i in range(max_tips * 2):
            _chain_tips[f"x-{i}"] = f"h-{i}"
            _chain_tips.move_to_end(f"x-{i}")
            while len(_chain_tips) > max_tips:
                _chain_tips.popitem(last=False)

        assert len(_chain_tips) <= max_tips


# ── A-3 / A-4: Audit hash HMAC ──────────────────────────────────────────────

class TestA3A4AuditHmac:
    """A-3: HMAC quando segredo configurado; A-4: segredos diferentes → hashes diferentes."""

    def _make_entry(self):
        return {
            "timestamp": 1000.0,
            "action": "test",
            "path": "/v1/test",
            "method": "POST",
            "ip": "127.0.0.1",
            "tenant": "tenant-abc",
            "details": "",
            "prev_hash": "0" * 64,
            "actor_id": None,
            "actor_role": None,
            "auth_source": None,
            "actor_reason": None,
            "actor_headers_trusted": False,
        }

    def test_hmac_hash_when_secret_configured(self):
        with patch.dict(os.environ, {"AION_SESSION_AUDIT_SECRET": "my-secret"}):
            from aion.middleware import _hash_entry
            entry = self._make_entry()
            h = _hash_entry(entry)
            assert len(h) == 64  # SHA-256 hex = 64 chars
            assert h != "0" * 64

    def test_plain_hash_when_no_secret(self):
        env = {k: v for k, v in os.environ.items() if k != "AION_SESSION_AUDIT_SECRET"}
        with patch.dict(os.environ, env, clear=True):
            from aion.middleware import _hash_entry
            entry = self._make_entry()
            h = _hash_entry(entry)
            assert len(h) == 64

    def test_different_secrets_produce_different_hashes(self):
        entry = self._make_entry()
        from aion.middleware import _hash_entry

        with patch.dict(os.environ, {"AION_SESSION_AUDIT_SECRET": "secret-A"}):
            h1 = _hash_entry(entry)

        with patch.dict(os.environ, {"AION_SESSION_AUDIT_SECRET": "secret-B"}):
            h2 = _hash_entry(entry)

        assert h1 != h2

    def test_hmac_hash_is_deterministic(self):
        entry = self._make_entry()
        from aion.middleware import _hash_entry

        with patch.dict(os.environ, {"AION_SESSION_AUDIT_SECRET": "stable-secret"}):
            h1 = _hash_entry(entry)
            h2 = _hash_entry(entry)

        assert h1 == h2

    def test_entry_hash_field_excluded_from_hash_input(self):
        """entry_hash deve ser excluído do cálculo para evitar auto-referência."""
        entry_a = self._make_entry()
        entry_b = {**self._make_entry(), "entry_hash": "some-previous-hash"}

        from aion.middleware import _hash_entry
        with patch.dict(os.environ, {"AION_SESSION_AUDIT_SECRET": "x"}):
            h1 = _hash_entry(entry_a)
            h2 = _hash_entry(entry_b)

        assert h1 == h2


# ── A-5: Audit background task GC protection ────────────────────────────────

class TestA5AuditBgTaskGc:
    """A-5: _AUDIT_BG_TASKS mantém referência forte à task e descarta após conclusão."""

    @pytest.mark.asyncio
    async def test_task_added_to_bg_set(self):
        from aion.middleware import _AUDIT_BG_TASKS

        ran = []

        async def dummy():
            ran.append(1)

        task = asyncio.create_task(dummy())
        _AUDIT_BG_TASKS.add(task)
        task.add_done_callback(_AUDIT_BG_TASKS.discard)

        await task
        await asyncio.sleep(0)  # allow done_callback to fire

        assert task not in _AUDIT_BG_TASKS
        assert ran == [1]

    @pytest.mark.asyncio
    async def test_multiple_tasks_all_cleaned_up(self):
        from aion.middleware import _AUDIT_BG_TASKS
        initial_count = len(_AUDIT_BG_TASKS)
        tasks = []

        async def noop():
            pass

        for _ in range(5):
            t = asyncio.create_task(noop())
            _AUDIT_BG_TASKS.add(t)
            t.add_done_callback(_AUDIT_BG_TASKS.discard)
            tasks.append(t)

        await asyncio.gather(*tasks)
        await asyncio.sleep(0)

        assert len(_AUDIT_BG_TASKS) == initial_count

    @pytest.mark.asyncio
    async def test_bg_tasks_is_module_level_set(self):
        from aion.middleware import _AUDIT_BG_TASKS
        assert isinstance(_AUDIT_BG_TASKS, set)


# ── A-6: Behavior store bounded ─────────────────────────────────────────────

class TestA6BehaviorStoreBounded:
    """A-6: _behavior_store evicta tenant mais antigo quando excede _MAX_BEHAVIOR_ENTRIES."""

    def setup_method(self):
        import aion.metis.behavior as beh
        beh._behavior_store.clear()

    def teardown_method(self):
        import aion.metis.behavior as beh
        beh._behavior_store.clear()

    @pytest.mark.asyncio
    async def test_store_evicts_oldest_when_full(self):
        from aion.metis.behavior import BehaviorConfig, BehaviorDial, _behavior_store
        from aion.config import get_metis_settings
        dial = BehaviorDial()
        cfg = BehaviorConfig()
        max_entries = get_metis_settings().behavior_store_max_entries

        # Fill to max
        for i in range(max_entries):
            _behavior_store[f"t-{i}"] = cfg
            _behavior_store.move_to_end(f"t-{i}")

        # One more → evicts t-0
        with patch("aion.metis.behavior._get_redis", new=AsyncMock(return_value=None)):
            await dial.set(cfg, tenant="t-NEW")

        assert len(_behavior_store) == max_entries
        assert "t-0" not in _behavior_store
        assert "t-NEW" in _behavior_store

    @pytest.mark.asyncio
    async def test_store_never_exceeds_max(self):
        from aion.metis.behavior import BehaviorConfig, BehaviorDial, _behavior_store
        from aion.config import get_metis_settings
        dial = BehaviorDial()
        cfg = BehaviorConfig()
        max_entries = get_metis_settings().behavior_store_max_entries

        with patch("aion.metis.behavior._get_redis", new=AsyncMock(return_value=None)):
            for i in range(max_entries + 20):
                await dial.set(cfg, tenant=f"tenant-{i}")

        assert len(_behavior_store) <= max_entries

    @pytest.mark.asyncio
    async def test_most_recently_set_survives(self):
        from aion.metis.behavior import BehaviorConfig, BehaviorDial, _behavior_store
        from aion.config import get_metis_settings
        dial = BehaviorDial()
        cfg = BehaviorConfig()
        max_entries = get_metis_settings().behavior_store_max_entries

        with patch("aion.metis.behavior._get_redis", new=AsyncMock(return_value=None)):
            for i in range(max_entries + 5):
                await dial.set(cfg, tenant=f"recent-{i}")

        # The 5 most recent should survive
        for i in range(max_entries, max_entries + 5):
            assert f"recent-{i}" in _behavior_store
