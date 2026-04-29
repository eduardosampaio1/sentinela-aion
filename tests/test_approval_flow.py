"""Tests for REQUEST_HUMAN_APPROVAL lifecycle — endpoints + sweep."""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient


_APPROVAL_TEST_KEY = "approval-test-admin"

@pytest.fixture
def client(monkeypatch):
    import os
    from unittest.mock import MagicMock
    from aion.license import LicenseState
    mock_lic = MagicMock()
    mock_lic.state = LicenseState.ACTIVE
    monkeypatch.setattr("aion.license.validate_license_or_abort", lambda: mock_lic)
    monkeypatch.setenv("AION_ADMIN_KEY", f"{_APPROVAL_TEST_KEY}:admin")
    from aion import config as cfg
    cfg._settings = None
    from aion.main import app
    with TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Authorization": f"Bearer {_APPROVAL_TEST_KEY}"},
    ) as c:
        yield c
    cfg._settings = None


@pytest.fixture
async def approval_in_nemos():
    """Factory: create an approval record directly in NEMOS."""
    created = []

    async def _make(
        tenant: str = "test",
        on_timeout: str = "block",
        ttl_seconds: int = 3600,
        risk: str = "medium",
    ) -> str:
        from aion.adapter.approval_executor import _approval_key
        from aion.nemos import get_nemos
        approval_id = f"apr_test_{uuid.uuid4().hex[:8]}"
        now = time.time()
        record = {
            "approval_request_id": approval_id,
            "tenant": tenant,
            "status": "pending",
            "created_at": now,
            "expires_at": now + ttl_seconds,
            "on_timeout": on_timeout,
            "risk_level": risk,
            "fallback_target": None,
            "original_request_id": "req_xyz",
            "polling_url": f"/v1/approvals/{approval_id}",
            "callback_url": None,
            "resolved_by": None,
            "resolved_at": None,
        }
        await get_nemos()._store.set_json(_approval_key(approval_id), record, ttl_seconds=86400)
        created.append(approval_id)
        return approval_id

    yield _make


# ── Endpoints ──

class TestApprovalEndpoints:
    def test_get_unknown_approval_returns_404(self, client: TestClient):
        resp = client.get("/v1/approvals/apr_does_not_exist")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_pending_approval(self, client: TestClient, approval_in_nemos):
        approval_id = await approval_in_nemos()
        resp = client.get(f"/v1/approvals/{approval_id}")
        assert resp.status_code == 200
        rec = resp.json()
        assert rec["approval_request_id"] == approval_id
        assert rec["status"] == "pending"

    @pytest.mark.asyncio
    async def test_resolve_approve(self, client: TestClient, approval_in_nemos):
        approval_id = await approval_in_nemos()
        _resolve_headers = {
            "Authorization": f"Bearer {_APPROVAL_TEST_KEY}",
            "X-Aion-Actor-Reason": "test approval resolution",
        }
        resp = client.post(
            f"/v1/approvals/{approval_id}/resolve",
            json={"status": "approved", "approver": "alice"},
            headers=_resolve_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["resolved_by"] == "alice"

        # Confirm persistence
        resp2 = client.get(f"/v1/approvals/{approval_id}")
        rec = resp2.json()
        assert rec["status"] == "approved"
        assert rec["resolved_by"] == "alice"

    @pytest.mark.asyncio
    async def test_resolve_deny(self, client: TestClient, approval_in_nemos):
        approval_id = await approval_in_nemos()
        resp = client.post(
            f"/v1/approvals/{approval_id}/resolve",
            json={"status": "denied", "approver": "bob"},
            headers={
                "Authorization": f"Bearer {_APPROVAL_TEST_KEY}",
                "X-Aion-Actor-Reason": "test denial",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "denied"

    @pytest.mark.asyncio
    async def test_resolve_invalid_status(self, client: TestClient, approval_in_nemos):
        approval_id = await approval_in_nemos()
        resp = client.post(
            f"/v1/approvals/{approval_id}/resolve",
            json={"status": "maybe", "approver": "x"},
            headers={
                "Authorization": f"Bearer {_APPROVAL_TEST_KEY}",
                "X-Aion-Actor-Reason": "test invalid status",
            },
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_resolve_twice_fails(self, client: TestClient, approval_in_nemos):
        approval_id = await approval_in_nemos()
        _resolve_headers = {
            "Authorization": f"Bearer {_APPROVAL_TEST_KEY}",
            "X-Aion-Actor-Reason": "test double resolve",
        }
        client.post(
            f"/v1/approvals/{approval_id}/resolve",
            json={"status": "approved", "approver": "alice"},
            headers=_resolve_headers,
        )
        resp2 = client.post(
            f"/v1/approvals/{approval_id}/resolve",
            json={"status": "denied", "approver": "bob"},
            headers=_resolve_headers,
        )
        assert resp2.status_code == 409  # already resolved

    @pytest.mark.asyncio
    async def test_list_by_tenant_and_status(self, client: TestClient, approval_in_nemos):
        aid = await approval_in_nemos(tenant="acme")
        resp = client.get("/v1/approvals?tenant=acme&status=pending")
        assert resp.status_code == 200
        body = resp.json()
        assert any(a["approval_request_id"] == aid for a in body["approvals"])


# ── Timeout sweep ──

class TestApprovalSweep:
    @pytest.mark.asyncio
    async def test_expired_with_on_timeout_block(self, approval_in_nemos):
        """Expired approval with on_timeout=block → status becomes 'expired'."""
        # Create already-expired approval by using negative TTL
        from aion.adapter.approval_executor import _approval_key
        from aion.main import _sweep_expired_approvals
        from aion.nemos import get_nemos

        aid = await approval_in_nemos(on_timeout="block", ttl_seconds=-10)

        resolved_count = await _sweep_expired_approvals()
        assert resolved_count >= 1

        rec = await get_nemos()._store.get_json(_approval_key(aid))
        assert rec["status"] == "expired"
        assert rec["resolved_by"] == "system:timeout"

    @pytest.mark.asyncio
    async def test_expired_with_fallback_timeout(self, approval_in_nemos):
        """Expired approval with on_timeout=fallback_llm → status 'timeout_fallback'."""
        from aion.adapter.approval_executor import _approval_key
        from aion.main import _sweep_expired_approvals
        from aion.nemos import get_nemos

        aid = await approval_in_nemos(on_timeout="fallback_llm", ttl_seconds=-10)

        await _sweep_expired_approvals()
        rec = await get_nemos()._store.get_json(_approval_key(aid))
        assert rec["status"] == "timeout_fallback"

    @pytest.mark.asyncio
    async def test_non_expired_unchanged(self, approval_in_nemos):
        """Approvals not yet expired are untouched by the sweep."""
        from aion.adapter.approval_executor import _approval_key
        from aion.main import _sweep_expired_approvals
        from aion.nemos import get_nemos

        aid = await approval_in_nemos(ttl_seconds=3600)  # 1 hour future
        await _sweep_expired_approvals()
        rec = await get_nemos()._store.get_json(_approval_key(aid))
        assert rec["status"] == "pending"
