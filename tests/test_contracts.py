"""Tests for formal contracts, RBAC, policy precedence, economics, and explainability."""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient

from aion.shared.contracts import (
    EstixeResult, EstixeAction,
    NomosResult,
    MetisResult,
    DecisionRecord,
    Role, check_permission, ROLE_PERMISSIONS,
    PolicySource, resolve_precedence,
)
from aion.middleware import _parse_key_roles, _resolve_permission
from aion.pipeline import build_pipeline
from aion.shared.schemas import (
    ChatCompletionResponse, ChatCompletionChoice, ChatMessage, UsageInfo,
)


# ══════════════════════════════════════════════
# Formal contracts
# ══════════════════════════════════════════════

class TestModuleContracts:

    def test_estixe_result_bypass(self):
        r = EstixeResult(action=EstixeAction.BYPASS, intent_detected="greeting", intent_confidence=0.95)
        assert r.action == EstixeAction.BYPASS
        assert r.intent_confidence == 0.95

    def test_estixe_result_block(self):
        r = EstixeResult(action=EstixeAction.BLOCK, block_reason="prompt injection", policy_matched=["block_injection"])
        assert r.block_reason == "prompt injection"
        assert "block_injection" in r.policy_matched

    def test_nomos_result(self):
        r = NomosResult(
            selected_model="gpt-4o-mini",
            selected_provider="openai",
            complexity_score=25.0,
            route_reason="simple_prompt",
            estimated_cost=0.00005,
        )
        assert r.selected_model == "gpt-4o-mini"
        assert r.estimated_cost == 0.00005

    def test_metis_result(self):
        r = MetisResult(tokens_before=500, tokens_after=350, tokens_saved=150, compression_applied=True)
        assert r.tokens_saved == 150

    def test_decision_record_complete(self):
        record = DecisionRecord(
            request_id="abc123",
            tenant="acme",
            timestamp=1234567890.0,
            decision="bypass",
            estixe=EstixeResult(action=EstixeAction.BYPASS, intent_detected="greeting"),
            nomos=None,
            metis=None,
            tokens_saved=100,
            cost_saved=0.001,
        )
        assert record.decision == "bypass"
        assert record.estixe.intent_detected == "greeting"
        assert record.nomos is None


# ══════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════

class TestRBAC:

    def test_admin_has_all_permissions(self):
        assert check_permission(Role.ADMIN, "killswitch:write")
        assert check_permission(Role.ADMIN, "data:delete")
        assert check_permission(Role.ADMIN, "audit:read")

    def test_operator_cannot_killswitch(self):
        assert not check_permission(Role.OPERATOR, "killswitch:write")
        assert not check_permission(Role.OPERATOR, "data:delete")

    def test_operator_can_manage_modules(self):
        assert check_permission(Role.OPERATOR, "modules:write")
        assert check_permission(Role.OPERATOR, "behavior:write")
        assert check_permission(Role.OPERATOR, "overrides:write")

    def test_viewer_read_only(self):
        assert check_permission(Role.VIEWER, "audit:read")
        assert check_permission(Role.VIEWER, "stats:read")
        assert not check_permission(Role.VIEWER, "overrides:write")
        assert not check_permission(Role.VIEWER, "behavior:write")
        assert not check_permission(Role.VIEWER, "killswitch:write")

    def test_unknown_role_has_no_permissions(self):
        assert not check_permission("hacker", "killswitch:write")

    def test_parse_key_roles(self):
        # F-01/F-02: result is now (Role, frozenset[tenants]); "*" = all tenants
        _parse_key_roles.cache_clear()
        result = _parse_key_roles("key1:admin,key2:operator,key3:viewer")
        assert result["key1"] == (Role.ADMIN, frozenset({"*"}))
        assert result["key2"] == (Role.OPERATOR, frozenset({"*"}))
        assert result["key3"] == (Role.VIEWER, frozenset({"*"}))

    def test_parse_key_roles_backward_compat(self):
        """F-20: legacy keys without :role suffix default to viewer (least privilege),
        not admin. Production profile rejects them entirely."""
        _parse_key_roles.cache_clear()
        result = _parse_key_roles("old-key-123")
        assert result["old-key-123"] == (Role.VIEWER, frozenset({"*"}))

    def test_parse_key_roles_mixed(self):
        _parse_key_roles.cache_clear()
        result = _parse_key_roles("admin-key:admin,simple-key")
        assert result["admin-key"] == (Role.ADMIN, frozenset({"*"}))
        # F-20: legacy bare key → viewer, not admin
        assert result["simple-key"] == (Role.VIEWER, frozenset({"*"}))

    def test_parse_key_roles_tenant_binding(self):
        """F-01/F-02: third segment binds key to specific tenants."""
        _parse_key_roles.cache_clear()
        result = _parse_key_roles("opkey:operator:acme;globex,vkey:viewer:*")
        assert result["opkey"] == (Role.OPERATOR, frozenset({"acme", "globex"}))
        assert result["vkey"] == (Role.VIEWER, frozenset({"*"}))

    def test_resolve_permission_killswitch(self):
        assert _resolve_permission("PUT", "/v1/killswitch") == "killswitch:write"

    def test_resolve_permission_audit(self):
        assert _resolve_permission("GET", "/v1/audit") == "audit:read"

    def test_resolve_permission_data_delete(self):
        assert _resolve_permission("DELETE", "/v1/data/tenant-x") == "data:delete"


# ══════════════════════════════════════════════
# RBAC integration (API level)
# ══════════════════════════════════════════════

class TestRBACIntegration:

    @pytest.fixture
    async def client(self):
        import os
        os.environ["AION_ADMIN_KEY"] = "admin-key:admin,viewer-key:viewer"
        import aion.config
        aion.config._settings = None
        import aion.middleware
        aion.middleware._redis_client = None
        aion.middleware._redis_available = False

        from aion.main import app
        import aion.main as main_mod
        if main_mod._pipeline is None:
            main_mod._pipeline = build_pipeline()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

        os.environ.pop("AION_ADMIN_KEY", None)
        aion.config._settings = None
        aion.middleware._redis_client = None
        aion.middleware._redis_available = False

    @pytest.mark.asyncio
    async def test_viewer_can_read_audit(self, client):
        resp = await client.get("/v1/audit", headers={"Authorization": "Bearer viewer-key"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_viewer_cannot_activate_killswitch(self, client):
        resp = await client.put("/v1/killswitch",
            json={"reason": "test"},
            headers={"Authorization": "Bearer viewer-key"})
        assert resp.status_code == 403
        assert "forbidden" in resp.json()["error"]["code"]

    @pytest.mark.asyncio
    async def test_admin_can_activate_killswitch(self, client):
        resp = await client.put("/v1/killswitch",
            json={"reason": "test"},
            headers={
                "Authorization": "Bearer admin-key",
                "X-Aion-Actor-Reason": "automated test - killswitch validation",
            })
        assert resp.status_code == 200
        # Cleanup
        await client.delete("/v1/killswitch", headers={
            "Authorization": "Bearer admin-key",
            "X-Aion-Actor-Reason": "automated test - cleanup",
        })


# ══════════════════════════════════════════════
# Policy precedence
# ══════════════════════════════════════════════

class TestPolicyPrecedence:

    def test_request_overrides_tenant(self):
        sources = {
            PolicySource.DEFAULT: "model-a",
            PolicySource.TENANT: "model-b",
            PolicySource.REQUEST: "model-c",
        }
        value, source = resolve_precedence(sources)
        assert value == "model-c"
        assert source == PolicySource.REQUEST

    def test_override_beats_config_file(self):
        sources = {
            PolicySource.CONFIG_FILE: 0.85,
            PolicySource.OVERRIDE: 0.90,
        }
        value, source = resolve_precedence(sources)
        assert value == 0.90
        assert source == PolicySource.OVERRIDE

    def test_default_when_nothing_else(self):
        sources = {
            PolicySource.DEFAULT: "fallback",
        }
        value, source = resolve_precedence(sources)
        assert value == "fallback"
        assert source == PolicySource.DEFAULT

    def test_none_values_skipped(self):
        sources = {
            PolicySource.DEFAULT: "a",
            PolicySource.TENANT: None,
            PolicySource.OVERRIDE: "b",
        }
        value, source = resolve_precedence(sources)
        assert value == "b"


# ══════════════════════════════════════════════
# Economics & Explainability endpoints
# ══════════════════════════════════════════════

class TestEconomicsAPI:

    @pytest.fixture
    async def client(self):
        from aion.main import app
        import aion.main as main_mod
        if main_mod._pipeline is None:
            main_mod._pipeline = build_pipeline()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_economics_endpoint(self, client):
        resp = await client.get("/v1/economics")
        assert resp.status_code == 200
        data = resp.json()
        assert "economics" in data
        assert "decisions" in data
        assert "latency" in data
        assert "llm_calls_avoided" in data["economics"]
        assert "cost_saved_usd" in data["economics"]

    @pytest.mark.asyncio
    async def test_explain_not_found(self, client):
        resp = await client.get("/v1/explain/nonexistent-id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is False

    @pytest.mark.asyncio
    async def test_tenant_metrics(self, client):
        resp = await client.get("/v1/metrics/tenant/test-tenant")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant"] == "test-tenant"
        assert "metrics" in data
