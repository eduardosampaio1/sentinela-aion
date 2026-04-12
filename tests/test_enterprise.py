"""Enterprise hardening tests — audit path, tenant isolation, middleware security."""

import pytest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from aion.middleware import _is_admin_path
from aion.pipeline import Pipeline, build_pipeline
from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatMessage,
    PipelineContext,
    UsageInfo,
)


# ══════════════════════════════════════════════
# Bug fix: /v1/audit path protection
# ══════════════════════════════════════════════

class TestAdminPathMatching:
    """Verify ALL admin endpoints are correctly identified."""

    def test_audit_exact_path(self):
        """BUG FIX: /v1/audit (without trailing slash) must be admin."""
        assert _is_admin_path("/v1/audit") is True

    def test_audit_with_slash(self):
        assert _is_admin_path("/v1/audit/") is True

    def test_killswitch(self):
        assert _is_admin_path("/v1/killswitch") is True

    def test_behavior(self):
        assert _is_admin_path("/v1/behavior") is True

    def test_overrides(self):
        assert _is_admin_path("/v1/overrides") is True

    def test_modules_toggle(self):
        assert _is_admin_path("/v1/modules/estixe/toggle") is True

    def test_estixe_reload(self):
        assert _is_admin_path("/v1/estixe/intents/reload") is True
        assert _is_admin_path("/v1/estixe/policies/reload") is True

    def test_data_deletion(self):
        assert _is_admin_path("/v1/data/some-tenant") is True

    def test_chat_is_not_admin(self):
        assert _is_admin_path("/v1/chat/completions") is False

    def test_health_is_not_admin(self):
        assert _is_admin_path("/health") is False

    def test_stats_is_not_admin(self):
        assert _is_admin_path("/v1/stats") is False

    def test_models_is_not_admin(self):
        assert _is_admin_path("/v1/models") is False


# ══════════════════════════════════════════════
# Tenant isolation in pipeline
# ══════════════════════════════════════════════

class TenantSwapModule:
    """Malicious module that tries to change tenant."""
    name = "tenant_swapper"
    async def process(self, request, context):
        context.tenant = "HIJACKED"
        return context


class TrackingModule:
    def __init__(self, name):
        self.name = name
    async def process(self, request, context):
        return context


class TestTenantIsolation:

    @pytest.mark.asyncio
    async def test_tenant_cannot_be_changed_by_module(self):
        """Pipeline enforces tenant immutability — module cannot hijack tenant."""
        pipeline = Pipeline()
        pipeline.register_pre(TenantSwapModule())
        pipeline.register_pre(TrackingModule("nomos"))

        ctx = PipelineContext(tenant="legitimate-corp")
        result = await pipeline.run_pre(
            ChatCompletionRequest(
                model="test",
                messages=[ChatMessage(role="user", content="test")],
            ),
            ctx,
        )

        # Tenant MUST remain the original — module's change is reverted
        assert result.tenant == "legitimate-corp"

    @pytest.mark.asyncio
    async def test_concurrent_tenants_isolated(self):
        """Concurrent requests from different tenants don't leak state."""
        import asyncio

        pipeline = Pipeline()
        pipeline.register_pre(TrackingModule("estixe"))

        async def run_for_tenant(tenant_id):
            ctx = PipelineContext(tenant=tenant_id)
            result = await pipeline.run_pre(
                ChatCompletionRequest(
                    model="test",
                    messages=[ChatMessage(role="user", content=f"query from {tenant_id}")],
                ),
                ctx,
            )
            return result.tenant

        # Run 20 concurrent requests from different tenants
        tenants = [f"tenant-{i}" for i in range(20)]
        results = await asyncio.gather(*[run_for_tenant(t) for t in tenants])

        # Each result must match its original tenant
        for expected, actual in zip(tenants, results):
            assert actual == expected, f"Tenant leak: expected {expected}, got {actual}"


# ══════════════════════════════════════════════
# Middleware auth enforcement
# ══════════════════════════════════════════════

class TestMiddlewareAuth:

    @pytest.fixture
    async def client(self):
        import os
        os.environ["AION_ADMIN_KEY"] = "test-admin-key-123"
        import aion.config
        aion.config._settings = None
        import aion.middleware
        aion.middleware._STORE_INITIALIZED = False
        aion.middleware._store = None

        from aion.main import app
        import aion.main as main_mod
        if main_mod._pipeline is None:
            main_mod._pipeline = build_pipeline()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

        os.environ.pop("AION_ADMIN_KEY", None)
        aion.config._settings = None
        aion.middleware._STORE_INITIALIZED = False

    @pytest.mark.asyncio
    async def test_admin_endpoint_requires_auth(self, client):
        """Admin endpoint without auth returns 401."""
        resp = await client.get("/v1/audit")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_endpoint_with_valid_key(self, client):
        """Admin endpoint with valid key succeeds."""
        resp = await client.get(
            "/v1/audit",
            headers={"Authorization": "Bearer test-admin-key-123"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_endpoint_with_invalid_key(self, client):
        """Admin endpoint with wrong key returns 401."""
        resp = await client.get(
            "/v1/audit",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_chat_endpoint_no_auth_required(self, client):
        """Chat endpoint works without admin auth."""
        mock_resp = ChatCompletionResponse(
            model="test",
            choices=[ChatCompletionChoice(
                message=ChatMessage(role="assistant", content="ok"),
            )],
            usage=UsageInfo(prompt_tokens=5, completion_tokens=1, total_tokens=6),
        )
        with patch("aion.main.forward_request", new_callable=AsyncMock) as mock_fwd:
            mock_fwd.return_value = mock_resp
            resp = await client.post("/v1/chat/completions", json={
                "model": "test",
                "messages": [{"role": "user", "content": "hi"}],
            })
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_tenant_rejected(self, client):
        """Invalid tenant format is rejected at middleware."""
        resp = await client.get(
            "/v1/stats",
            headers={"X-Aion-Tenant": "../../etc/passwd"},
        )
        assert resp.status_code == 400
        assert "invalid_tenant" in resp.json()["error"]["code"]
