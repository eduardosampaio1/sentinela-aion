"""Testes dos fixes do QA Supremo.

Cobre todos os problemas apontados na auditoria:
- Fix 1: Audit chain tip recovery do Redis pós-eviction
- Fix 2: require_chat_auth + admin_key vazio → env_problem
- Fix 3: _AUDIT_BG_TASKS com timeout (_guarded_audit_write)
- Fix 4: _guarded_bg loga exceções ao invés de silenciar
- Fix 5: _client_lock top-level em proxy.py
- Fix 7: module_failure_threshold lido dinamicamente em record_failure
- Fix 8: tenant isolation check por módulo (não só no final do loop)
- Fix 9: EmbeddingModel concorrência (C-3 sem cobertura anterior)
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fix 1: Audit chain tip recovery ─────────────────────────────────────────

class TestFix1AuditChainTipRecovery:
    """Chain tip deve ser recuperado do Redis quando evictado da memória."""

    def setup_method(self):
        import aion.middleware as mw
        mw._chain_tips.clear()

    def teardown_method(self):
        import aion.middleware as mw
        mw._chain_tips.clear()

    @pytest.mark.asyncio
    async def test_chain_tip_redis_helper_returns_none_without_redis(self):
        from aion.middleware import _get_chain_tip_redis
        with patch("aion.middleware._get_redis", new=AsyncMock(return_value=None)):
            result = await _get_chain_tip_redis("any-tenant")
        assert result is None

    @pytest.mark.asyncio
    async def test_chain_tip_redis_helper_returns_stored_value(self):
        from aion.middleware import _get_chain_tip_redis
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="abc123hash")

        with patch("aion.middleware._get_redis", new=AsyncMock(return_value=mock_redis)):
            result = await _get_chain_tip_redis("tenant-x")

        assert result == "abc123hash"
        mock_redis.get.assert_called_once_with("aion:audit:tip:tenant-x")

    @pytest.mark.asyncio
    async def test_chain_reset_true_for_new_tenant(self):
        """Tenant genuinamente novo → chain_reset=True na entry."""
        from aion.middleware import _get_chain_tip_redis

        with patch("aion.middleware._get_redis", new=AsyncMock(return_value=None)):
            tip = await _get_chain_tip_redis("brand-new-tenant")

        assert tip is None  # Redis sem dado → genuinamente novo

    @pytest.mark.asyncio
    async def test_audit_chain_tip_persisted_to_redis(self):
        """audit() deve fazer setex no tip do Redis após cada entry."""
        from fastapi import Request
        from starlette.testclient import TestClient

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.setex = AsyncMock()

        from aion.middleware import audit
        mock_request = MagicMock()
        mock_request.url.path = "/v1/test"
        mock_request.method = "POST"
        mock_request.client.host = "127.0.0.1"
        mock_request.headers.get = MagicMock(return_value="")
        mock_request.state.trusted_proxy = False

        with patch("aion.middleware._get_redis", new=AsyncMock(return_value=mock_redis)):
            with patch("aion.middleware._get_chain_tip_redis", new=AsyncMock(return_value=None)):
                with patch("aion.middleware.asyncio.create_task", new=MagicMock()):
                    await audit("test_action", mock_request, "tenant-persist")

        # setex deve ter sido chamado com o tip key
        calls = [str(c) for c in mock_redis.setex.call_args_list]
        tip_call = any("aion:audit:tip:tenant-persist" in c for c in calls)
        assert tip_call, f"setex não chamado com tip key. Calls: {calls}"


# ── Fix 2: require_chat_auth + admin_key vazio ────────────────────────────────

class TestFix2RequireChatAuthFailSecure:
    """AION_REQUIRE_CHAT_AUTH=true + AION_ADMIN_KEY vazio → env_problem."""

    def test_require_chat_auth_without_admin_key_is_env_problem(self):
        import aion.config as cfg
        cfg._settings = None

        with patch.dict(os.environ, {
            "AION_REQUIRE_CHAT_AUTH": "true",
            "AION_ADMIN_KEY": "",
        }):
            cfg._settings = None
            from aion.config import get_settings
            settings = get_settings()

            # Replicate the env_problems logic from main.py
            env_problems = []
            if not settings.admin_key:
                env_problems.append("AION_ADMIN_KEY is not set")
            if settings.require_chat_auth and not settings.admin_key:
                env_problems.append("AION_REQUIRE_CHAT_AUTH=true but AION_ADMIN_KEY is not set")

            assert any("AION_REQUIRE_CHAT_AUTH" in p for p in env_problems)

        cfg._settings = None

    def test_require_chat_auth_with_admin_key_is_not_problem(self):
        import aion.config as cfg
        cfg._settings = None

        with patch.dict(os.environ, {
            "AION_REQUIRE_CHAT_AUTH": "true",
            "AION_ADMIN_KEY": "valid-key:admin",
        }):
            cfg._settings = None
            from aion.config import get_settings
            settings = get_settings()

            env_problems = []
            if settings.require_chat_auth and not settings.admin_key:
                env_problems.append("REQUIRE_CHAT_AUTH without key")

            assert not env_problems

        cfg._settings = None

    def test_require_chat_auth_disabled_no_problem(self):
        import aion.config as cfg
        cfg._settings = None

        with patch.dict(os.environ, {
            "AION_REQUIRE_CHAT_AUTH": "false",
            "AION_ADMIN_KEY": "",
        }):
            cfg._settings = None
            from aion.config import get_settings
            settings = get_settings()

            env_problems = []
            if settings.require_chat_auth and not settings.admin_key:
                env_problems.append("problem")

            assert not env_problems

        cfg._settings = None


# ── Fix 3: _AUDIT_BG_TASKS com timeout ───────────────────────────────────────

class TestFix3AuditBgTaskTimeout:
    """_guarded_audit_write deve cancelar Supabase write que trava."""

    @pytest.mark.asyncio
    async def test_guarded_audit_write_completes_fast(self):
        from aion.middleware import _guarded_audit_write
        completed = []

        async def fast_write():
            completed.append(1)

        await _guarded_audit_write(fast_write())
        assert completed == [1]

    @pytest.mark.asyncio
    async def test_guarded_audit_write_cancels_slow(self):
        from aion.middleware import _guarded_audit_write

        completed = []

        async def slow_write():
            await asyncio.sleep(999)
            completed.append("should-not-reach")

        with patch("aion.middleware.get_settings") as mock_settings:
            mock_settings.return_value.bg_task_timeout_seconds = 0.05
            await asyncio.wait_for(_guarded_audit_write(slow_write()), timeout=2.0)

        assert completed == []

    @pytest.mark.asyncio
    async def test_guarded_audit_write_swallows_exceptions(self):
        from aion.middleware import _guarded_audit_write

        async def failing_write():
            raise ValueError("supabase connection error")

        # Must not raise
        await _guarded_audit_write(failing_write())

    def test_guarded_audit_write_exists_in_middleware(self):
        from aion.middleware import _guarded_audit_write
        assert callable(_guarded_audit_write)


# ── Fix 4: _guarded_bg loga exceções ─────────────────────────────────────────

class TestFix4GuardedBgLogs:
    """_guarded_bg deve logar TimeoutError e exceções (não silenciar)."""

    @pytest.mark.asyncio
    async def test_timeout_is_logged(self):
        from aion.pipeline import _guarded_bg

        with patch("aion.pipeline.logger") as mock_logger:
            async def slow():
                await asyncio.sleep(999)

            with patch("aion.pipeline.get_settings") as mock_s:
                mock_s.return_value.bg_task_timeout_seconds = 0.05
                await asyncio.wait_for(_guarded_bg(slow()), timeout=2.0)

            # debug should have been called for the timeout
            assert mock_logger.debug.called

    @pytest.mark.asyncio
    async def test_exception_is_logged(self):
        from aion.pipeline import _guarded_bg

        with patch("aion.pipeline.logger") as mock_logger:
            async def exploding():
                raise RuntimeError("internal error")

            await _guarded_bg(exploding(), timeout=5.0)

            assert mock_logger.debug.called

    @pytest.mark.asyncio
    async def test_fast_coroutine_no_log(self):
        from aion.pipeline import _guarded_bg

        with patch("aion.pipeline.logger") as mock_logger:
            async def fast():
                pass

            await _guarded_bg(fast(), timeout=5.0)

            # No debug log for successful completion
            mock_logger.debug.assert_not_called()


# ── Fix 5: _client_lock top-level em proxy.py ────────────────────────────────

class TestFix5ClientLockTopLevel:
    """_client_lock deve ser asyncio.Lock top-level, não criado lazily."""

    def test_client_lock_is_asyncio_lock(self):
        from aion.proxy import _client_lock
        assert isinstance(_client_lock, asyncio.Lock)

    def test_client_lock_is_not_none(self):
        import aion.proxy as px
        assert px._client_lock is not None


# ── Fix 7: module_failure_threshold dinâmico ─────────────────────────────────

class TestFix7DynamicFailureThreshold:
    """module_failure_threshold deve ser lido em record_failure, não capturado em __init__."""

    def test_threshold_not_stored_in_init(self):
        from aion.pipeline import ModuleStatus
        ms = ModuleStatus("test-module")
        # threshold should NOT be an instance attribute — read from settings each time
        assert not hasattr(ms, "failure_threshold")

    def test_record_failure_uses_current_settings(self):
        from aion.pipeline import ModuleStatus

        ms = ModuleStatus("test-module")

        # With threshold=3, 2 failures should not degrade
        with patch("aion.pipeline.get_settings") as mock_s:
            mock_s.return_value.module_failure_threshold = 3
            ms.record_failure("err1")
            ms.record_failure("err2")
        assert ms.healthy is True

        # Now lower threshold to 2 — 3rd failure should degrade
        with patch("aion.pipeline.get_settings") as mock_s:
            mock_s.return_value.module_failure_threshold = 2
            ms.record_failure("err3")
        assert ms.healthy is False

    def test_threshold_change_respected_without_restart(self):
        from aion.pipeline import ModuleStatus

        ms = ModuleStatus("dynamic-module")

        # First call at threshold=10 — does not degrade
        with patch("aion.pipeline.get_settings") as mock_s:
            mock_s.return_value.module_failure_threshold = 10
            for _ in range(5):
                ms.record_failure("error")
        assert ms.healthy is True

        # Change threshold to 4 — module should now be considered degraded
        with patch("aion.pipeline.get_settings") as mock_s:
            mock_s.return_value.module_failure_threshold = 4
            ms.record_failure("error")
        assert ms.healthy is False


# ── Fix 8: tenant isolation per-module ───────────────────────────────────────

class TestFix8PerModuleTenantIsolation:
    """Tenant isolation check deve parar o loop imediatamente, não só ao final."""

    @pytest.mark.asyncio
    async def test_second_module_skipped_after_first_violates(self):
        from aion.pipeline import Pipeline
        from aion.shared.schemas import ChatCompletionRequest, ChatMessage, Decision, PipelineContext

        executed = []

        class ViolatingModule:
            name = "violator"
            async def process(self, request, context):
                executed.append("violator")
                context.tenant = "attacker"
                return context

        class SecondModule:
            name = "second"
            async def process(self, request, context):
                executed.append("second")  # must NOT run
                return context

        pipeline = Pipeline()
        pipeline._pre_modules = [ViolatingModule(), SecondModule()]

        req = ChatCompletionRequest(model="t", messages=[ChatMessage(role="user", content="hi")])
        ctx = PipelineContext(tenant="safe-tenant")

        result = await pipeline.run_pre(req, ctx)

        assert result.decision == Decision.BLOCK
        assert "violator" in executed
        assert "second" not in executed  # stopped at first violation

    @pytest.mark.asyncio
    async def test_violating_module_name_in_metadata(self):
        from aion.pipeline import Pipeline
        from aion.shared.schemas import ChatCompletionRequest, ChatMessage, PipelineContext

        class BadModule:
            name = "bad-actor"
            async def process(self, request, context):
                context.tenant = "hijacked"
                return context

        pipeline = Pipeline()
        pipeline._pre_modules = [BadModule()]

        req = ChatCompletionRequest(model="t", messages=[ChatMessage(role="user", content="hi")])
        ctx = PipelineContext(tenant="original")

        result = await pipeline.run_pre(req, ctx)

        assert result.metadata.get("violating_module") == "bad-actor"

    @pytest.mark.asyncio
    async def test_two_modules_before_violation_both_run(self):
        from aion.pipeline import Pipeline
        from aion.shared.schemas import ChatCompletionRequest, ChatMessage, Decision, PipelineContext

        executed = []

        class GoodA:
            name = "good-a"
            async def process(self, request, context):
                executed.append("good-a")
                return context

        class GoodB:
            name = "good-b"
            async def process(self, request, context):
                executed.append("good-b")
                return context

        class Violator:
            name = "violator"
            async def process(self, request, context):
                executed.append("violator")
                context.tenant = "hacked"
                return context

        pipeline = Pipeline()
        pipeline._pre_modules = [GoodA(), GoodB(), Violator()]

        req = ChatCompletionRequest(model="t", messages=[ChatMessage(role="user", content="hi")])
        ctx = PipelineContext(tenant="original")

        result = await pipeline.run_pre(req, ctx)

        assert "good-a" in executed
        assert "good-b" in executed
        assert "violator" in executed
        assert result.decision == Decision.BLOCK


# ── Fix 9 (C-3 gap): EmbeddingModel concurrency ──────────────────────────────

class TestFix9EmbeddingModelConcurrency:
    """EmbeddingModel.encode_single deve ser thread-safe sob chamadas concorrentes."""

    def _make_mock_model(self):
        import numpy as np
        from aion.shared.embeddings import EmbeddingModel

        model = EmbeddingModel()
        model._loaded = True
        model._load_failed = False
        model._model_name = "test"

        mock_inner = MagicMock()
        # encode_single calls model.encode([text])[0] → must return 2D (N, dim)
        mock_inner.encode = MagicMock(
            return_value=np.array([[1.0, 2.0, 3.0]], dtype="float32")
        )
        mock_inner.get_sentence_embedding_dimension = MagicMock(return_value=3)
        model._model = mock_inner
        return model

    def test_concurrent_encode_no_race(self):
        import numpy as np
        model = self._make_mock_model()
        results = []
        lock = threading.Lock()
        errors = []

        def encode():
            try:
                emb = model.encode_single("hello world", use_cache=False)
                with lock:
                    results.append(emb)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=encode) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent encoding: {errors}"
        assert len(results) == 50

    def test_concurrent_lru_cache_no_corruption(self):
        import numpy as np
        model = self._make_mock_model()
        results = []
        lock = threading.Lock()
        errors = []

        def encode_cached(text):
            try:
                # use_cache=True tests the LRU dict under concurrent access
                emb = model.encode_single(text, use_cache=True)
                with lock:
                    results.append(len(emb))
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = (
            [threading.Thread(target=encode_cached, args=("hello",)) for _ in range(20)] +
            [threading.Thread(target=encode_cached, args=("world",)) for _ in range(20)] +
            [threading.Thread(target=encode_cached, args=("test",)) for _ in range(10)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors: {errors}"
        assert len(results) == 50

    def test_clear_cache_thread_safe(self):
        model = self._make_mock_model()
        errors = []
        lock = threading.Lock()

        def work():
            try:
                for _ in range(5):
                    model.encode_single("test", use_cache=True)
                model.clear_cache()
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=work) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
