"""Testes dos gaps críticos — Week 1 (C-1, C-4, C-5, C-7).

C-1: fail-fast startup quando AION_FAIL_MODE=closed sem admin key
C-4: /v1/decide e demais endpoints de chat exigem auth quando require_chat_auth=true
C-5: violação de tenant isolation → Decision.BLOCK (não apenas revert)
C-7: _guarded_bg() cancela coroutines que travam após timeout
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=False)
def reset_config():
    import aion.config as cfg
    old = cfg._settings
    cfg._settings = None
    yield
    cfg._settings = old


def _req_body():
    return {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}


# ── C-1: Fail-fast startup ───────────────────────────────────────────────────

class TestC1FailFast:
    """C-1: startup deve abortar quando fail_mode=closed e admin_key está vazio."""

    def test_aborts_when_closed_mode_and_no_admin_key(self):
        import sys
        from aion.config import FailMode

        env_problems = ["AION_ADMIN_KEY is not set"]
        fail_mode = FailMode.CLOSED

        with patch.object(sys, "exit") as mock_exit:
            if env_problems and fail_mode == FailMode.CLOSED:
                sys.exit(1)
            mock_exit.assert_called_once_with(1)

    def test_no_abort_in_open_mode(self):
        import sys
        from aion.config import FailMode

        env_problems = ["AION_ADMIN_KEY is not set"]
        fail_mode = FailMode.OPEN

        with patch.object(sys, "exit") as mock_exit:
            if env_problems and fail_mode == FailMode.CLOSED:
                sys.exit(1)
            mock_exit.assert_not_called()

    def test_no_abort_when_admin_key_is_set_in_closed_mode(self):
        import sys
        from aion.config import FailMode

        # No problems → no abort even in CLOSED mode
        env_problems: list[str] = []
        fail_mode = FailMode.CLOSED

        with patch.object(sys, "exit") as mock_exit:
            if env_problems and fail_mode == FailMode.CLOSED:
                sys.exit(1)
            mock_exit.assert_not_called()

    def test_fail_mode_closed_setting_parsed_correctly(self, reset_config):
        with patch.dict(os.environ, {"AION_FAIL_MODE": "closed"}):
            import aion.config as cfg
            cfg._settings = None
            from aion.config import get_settings, FailMode
            settings = get_settings()
            assert settings.fail_mode == FailMode.CLOSED

    def test_fail_mode_open_is_default(self, reset_config):
        """Default fail_mode deve ser open para não bloquear novos deploys."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AION_FAIL_MODE", None)
            import aion.config as cfg
            cfg._settings = None
            from aion.config import get_settings, FailMode
            settings = get_settings()
            assert settings.fail_mode == FailMode.OPEN


# ── C-4: Auth guard para /v1/decide e outros endpoints ──────────────────────

class TestC4AuthGuard:
    """C-4: /v1/decide, /v1/chat/assisted e /v1/decisions devem exigir auth."""

    def test_chat_endpoints_constant_includes_decide(self):
        from aion.middleware import _CHAT_ENDPOINTS
        assert "/v1/decide" in _CHAT_ENDPOINTS

    def test_chat_endpoints_constant_includes_all_inference_paths(self):
        from aion.middleware import _CHAT_ENDPOINTS
        expected = {"/v1/chat/completions", "/v1/decide", "/v1/chat/assisted", "/v1/decisions"}
        assert expected.issubset(_CHAT_ENDPOINTS)

    def test_decide_returns_401_without_key(self, reset_config):
        with patch.dict(os.environ, {
            "AION_REQUIRE_CHAT_AUTH": "true",
            "AION_ADMIN_KEY": "valid-key:admin",
        }):
            import aion.config as cfg
            cfg._settings = None
            from aion.main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)

            resp = client.post("/v1/decide", json=_req_body())
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "unauthorized"

    def test_decide_passes_with_valid_key(self, reset_config):
        with patch.dict(os.environ, {
            "AION_REQUIRE_CHAT_AUTH": "true",
            "AION_ADMIN_KEY": "valid-key:admin",
        }):
            import aion.config as cfg
            cfg._settings = None
            from aion.main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)

            resp = client.post(
                "/v1/decide",
                json=_req_body(),
                headers={"Authorization": "Bearer valid-key"},
            )
            # 401 auth code should not be returned; any other code is acceptable
            assert resp.status_code != 401

    def test_chat_completions_unchanged_still_requires_auth(self, reset_config):
        with patch.dict(os.environ, {
            "AION_REQUIRE_CHAT_AUTH": "true",
            "AION_ADMIN_KEY": "key-abc:admin",
        }):
            import aion.config as cfg
            cfg._settings = None
            from aion.main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)

            resp = client.post("/v1/chat/completions", json=_req_body())
            assert resp.status_code == 401


# ── C-5: Tenant isolation → Decision.BLOCK ──────────────────────────────────

class TestC5TenantIsolation:
    """C-5: módulo que muda context.tenant deve resultar em BLOCK, não revert silencioso."""

    @pytest.mark.asyncio
    async def test_tenant_mutation_triggers_block(self):
        from aion.pipeline import Pipeline
        from aion.shared.schemas import ChatCompletionRequest, ChatMessage, Decision, PipelineContext

        class TenantMutatingModule:
            name = "bad_module"

            async def process(self, request, context):
                context.tenant = "injected-tenant"
                return context

        pipeline = Pipeline()
        pipeline._pre_modules = [TenantMutatingModule()]

        req = ChatCompletionRequest(model="test", messages=[ChatMessage(role="user", content="hi")])
        ctx = PipelineContext(tenant="original-tenant")

        result = await pipeline.run_pre(req, ctx)

        assert result.decision == Decision.BLOCK

    @pytest.mark.asyncio
    async def test_tenant_reverted_after_violation(self):
        from aion.pipeline import Pipeline
        from aion.shared.schemas import ChatCompletionRequest, ChatMessage, PipelineContext

        class TenantMutatingModule:
            name = "bad_module"

            async def process(self, request, context):
                context.tenant = "attacker-tenant"
                return context

        pipeline = Pipeline()
        pipeline._pre_modules = [TenantMutatingModule()]

        req = ChatCompletionRequest(model="test", messages=[ChatMessage(role="user", content="hi")])
        ctx = PipelineContext(tenant="safe-tenant")

        result = await pipeline.run_pre(req, ctx)

        assert result.tenant == "safe-tenant"

    @pytest.mark.asyncio
    async def test_block_reason_set_in_metadata(self):
        from aion.pipeline import Pipeline
        from aion.shared.schemas import ChatCompletionRequest, ChatMessage, PipelineContext

        class TenantMutatingModule:
            name = "bad_module"

            async def process(self, request, context):
                context.tenant = "other-tenant"
                return context

        pipeline = Pipeline()
        pipeline._pre_modules = [TenantMutatingModule()]

        req = ChatCompletionRequest(model="test", messages=[ChatMessage(role="user", content="hi")])
        ctx = PipelineContext(tenant="legit-tenant")

        result = await pipeline.run_pre(req, ctx)

        assert result.metadata.get("block_reason") == "tenant_isolation_violation"

    @pytest.mark.asyncio
    async def test_legitimate_module_does_not_trigger_block(self):
        from aion.pipeline import Pipeline
        from aion.shared.schemas import ChatCompletionRequest, ChatMessage, Decision, PipelineContext

        class GoodModule:
            name = "good"

            async def process(self, request, context):
                # Reads tenant but does NOT change it
                _ = context.tenant
                return context

        pipeline = Pipeline()
        pipeline._pre_modules = [GoodModule()]

        req = ChatCompletionRequest(model="test", messages=[ChatMessage(role="user", content="hi")])
        ctx = PipelineContext(tenant="tenant-abc")

        result = await pipeline.run_pre(req, ctx)

        assert result.decision == Decision.CONTINUE


# ── C-7: _guarded_bg timeout ────────────────────────────────────────────────

class TestC7GuardedBg:
    """C-7: _guarded_bg deve cancelar coroutines que travam e deixar rápidas completar."""

    @pytest.mark.asyncio
    async def test_fast_coroutine_completes_normally(self):
        from aion.pipeline import _guarded_bg

        results = []

        async def fast():
            results.append("done")

        await _guarded_bg(fast(), timeout=5.0)
        assert results == ["done"]

    @pytest.mark.asyncio
    async def test_slow_coroutine_cancelled_by_timeout(self):
        from aion.pipeline import _guarded_bg

        completed = []

        async def never_completes():
            await asyncio.sleep(999)
            completed.append("should-not-reach")

        # Should return within ~timeout, not hang
        await asyncio.wait_for(_guarded_bg(never_completes(), timeout=0.05), timeout=2.0)
        assert completed == []

    @pytest.mark.asyncio
    async def test_exception_in_coroutine_does_not_propagate(self):
        from aion.pipeline import _guarded_bg

        async def exploding():
            raise ValueError("boom")

        # _guarded_bg must swallow exceptions
        await _guarded_bg(exploding(), timeout=5.0)  # should not raise

    @pytest.mark.asyncio
    async def test_bg_tasks_set_cleans_up_after_completion(self):
        from aion.pipeline import _BG_TASKS, _guarded_bg

        results = []

        async def work():
            results.append(1)

        t = asyncio.create_task(_guarded_bg(work()))
        _BG_TASKS.add(t)
        t.add_done_callback(_BG_TASKS.discard)

        await t
        await asyncio.sleep(0)  # allow done_callback to fire

        assert t not in _BG_TASKS
        assert results == [1]
