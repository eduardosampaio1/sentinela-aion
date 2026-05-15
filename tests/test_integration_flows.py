"""Integration tests for RBAC enforcement on admin endpoints (BUG-004).

These tests MUST fail if authentication is removed or weakened.
They prove that killswitch and LGPD delete require valid admin credentials.
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient


def _reset_middleware_state():
    """Clear rate limiter and redis state to avoid 429 between tests."""
    import aion.middleware as mw
    mw._local_rate_limits.clear()
    mw._redis_client = None
    mw._redis_available = False


def _make_client_no_key():
    """Helper: returns async context manager with no admin key configured."""
    import aion.config
    os.environ.pop("AION_ADMIN_KEY", None)
    aion.config._settings = None
    _reset_middleware_state()

    from aion.main import app
    import aion.main as main_mod
    from aion.pipeline import build_pipeline
    if main_mod._pipeline is None:
        main_mod._pipeline = build_pipeline()

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _make_client_with_key():
    """Helper: returns async context manager with admin-key:admin,operator-key:operator."""
    os.environ["AION_ADMIN_KEY"] = "admin-key:admin,operator-key:operator"
    import aion.config
    aion.config._settings = None
    _reset_middleware_state()

    from aion.main import app
    import aion.main as main_mod
    from aion.pipeline import build_pipeline
    if main_mod._pipeline is None:
        main_mod._pipeline = build_pipeline()

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestRBAC:
    """RBAC enforcement on killswitch and LGPD delete.

    Each test is self-contained — manages its own env + config reset.
    Tests that check rejection must NOT use skip/xfail.
    """

    # ── Kill switch — no key configured ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_admin_endpoint_without_key_rejected(self):
        """BUG-004: killswitch must be blocked when AION_ADMIN_KEY not set."""
        async with _make_client_no_key() as client:
            resp = await client.put(
                "/v1/killswitch",
                json={"reason": "test"},
                headers={"Authorization": "Bearer wrong-key"},
            )
        assert resp.status_code in (401, 403), (
            f"Kill switch aceito sem auth válida — status={resp.status_code}, body={resp.text}"
        )
        import aion.config
        aion.config._settings = None

    @pytest.mark.asyncio
    async def test_killswitch_delete_without_key_rejected(self):
        """BUG-004: killswitch DELETE must be blocked when AION_ADMIN_KEY not set."""
        async with _make_client_no_key() as client:
            resp = await client.delete(
                "/v1/killswitch",
                headers={"Authorization": "Bearer anything"},
            )
        assert resp.status_code in (401, 403)
        import aion.config
        aion.config._settings = None

    # ── Kill switch — key configured, wrong token ─────────────────────────────

    @pytest.mark.asyncio
    async def test_killswitch_with_wrong_key_rejected(self):
        """Kill switch with invalid bearer token must return 401."""
        async with _make_client_with_key() as client:
            resp = await client.put(
                "/v1/killswitch",
                json={"reason": "test"},
                headers={"Authorization": "Bearer wrong-key"},
            )
        assert resp.status_code == 401
        os.environ.pop("AION_ADMIN_KEY", None)
        import aion.config
        aion.config._settings = None

    @pytest.mark.asyncio
    async def test_killswitch_without_auth_header_rejected(self):
        """Kill switch with no Authorization header must return 401."""
        async with _make_client_with_key() as client:
            resp = await client.put("/v1/killswitch", json={"reason": "test"})
        assert resp.status_code == 401
        os.environ.pop("AION_ADMIN_KEY", None)
        import aion.config
        aion.config._settings = None

    # ── Kill switch — RBAC: insufficient role ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_killswitch_with_operator_key_forbidden(self):
        """Kill switch with operator-role key must return 403 (lacks killswitch:write)."""
        async with _make_client_with_key() as client:
            resp = await client.put(
                "/v1/killswitch",
                json={"reason": "test"},
                headers={"Authorization": "Bearer operator-key"},
            )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"
        os.environ.pop("AION_ADMIN_KEY", None)
        import aion.config
        aion.config._settings = None

    # ── Kill switch — valid admin key ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_killswitch_with_valid_admin_key_succeeds(self):
        """Kill switch with valid admin key must succeed."""
        async with _make_client_with_key() as client:
            resp = await client.put(
                "/v1/killswitch",
                json={"reason": "rbac-test"},
                headers={
                    "Authorization": "Bearer admin-key",
                    "X-Aion-Actor-Reason": "rbac-test",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["killswitch_active"] is True
            # Cleanup: deactivate so other tests aren't affected
            await client.delete(
                "/v1/killswitch",
                headers={
                    "Authorization": "Bearer admin-key",
                    "X-Aion-Actor-Reason": "cleanup",
                },
            )
        os.environ.pop("AION_ADMIN_KEY", None)
        import aion.config
        aion.config._settings = None

    # ── LGPD delete — no key configured ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_data_delete_without_key_rejected(self):
        """BUG-004: LGPD delete must be blocked when AION_ADMIN_KEY not set."""
        async with _make_client_no_key() as client:
            resp = await client.delete(
                "/v1/data/any-tenant",
                headers={"Authorization": "Bearer wrong-key"},
            )
        assert resp.status_code in (401, 403), (
            f"Data delete aceito sem auth válida — status={resp.status_code}, body={resp.text}"
        )
        import aion.config
        aion.config._settings = None

    @pytest.mark.asyncio
    async def test_data_delete_no_auth_header_without_key_rejected(self):
        """LGPD delete with no header AND no key configured must be blocked."""
        async with _make_client_no_key() as client:
            resp = await client.delete("/v1/data/any-tenant")
        assert resp.status_code in (401, 403)
        import aion.config
        aion.config._settings = None

    # ── LGPD delete — key configured, wrong token ────────────────────────────

    @pytest.mark.asyncio
    async def test_data_delete_with_wrong_key_rejected(self):
        """LGPD delete with invalid bearer token must return 401."""
        async with _make_client_with_key() as client:
            resp = await client.delete(
                "/v1/data/any-tenant",
                headers={
                    "Authorization": "Bearer wrong-key",
                    "X-Aion-Tenant": "any-tenant",
                },
            )
        assert resp.status_code == 401
        os.environ.pop("AION_ADMIN_KEY", None)
        import aion.config
        aion.config._settings = None

    # ── LGPD delete — RBAC: insufficient role ────────────────────────────────

    @pytest.mark.asyncio
    async def test_data_delete_with_operator_key_forbidden(self):
        """LGPD delete with operator key must return 403 (lacks data:delete)."""
        async with _make_client_with_key() as client:
            resp = await client.delete(
                "/v1/data/test-tenant",
                headers={
                    "Authorization": "Bearer operator-key",
                    "X-Aion-Tenant": "test-tenant",
                },
            )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"
        os.environ.pop("AION_ADMIN_KEY", None)
        import aion.config
        aion.config._settings = None

    # ── LGPD delete — valid admin key ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_data_delete_with_valid_admin_key_succeeds(self):
        """LGPD delete with valid admin key must succeed (idempotent for unknown tenant)."""
        async with _make_client_with_key() as client:
            resp = await client.delete(
                "/v1/data/rbac-test-tenant",
                headers={
                    "Authorization": "Bearer admin-key",
                    "X-Aion-Tenant": "rbac-test-tenant",
                    "X-Aion-Actor-Reason": "rbac-test deletion",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        os.environ.pop("AION_ADMIN_KEY", None)
        import aion.config
        aion.config._settings = None

    # ── Auth_not_configured error shape ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_auth_not_configured_error_shape(self):
        """When no key is configured, error body must have code=auth_not_configured."""
        async with _make_client_no_key() as client:
            resp = await client.put(
                "/v1/killswitch",
                json={"reason": "test"},
                headers={"Authorization": "Bearer x"},
            )
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "auth_not_configured"
        import aion.config
        aion.config._settings = None
