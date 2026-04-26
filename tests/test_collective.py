"""Smoke tests for the AION Collective editorial exchange router.

Tests:
- GET /v1/collective/policies  → returns 6 editorial policies
- GET /v1/collective/policies/{id} → returns provenance for a known policy
- GET /v1/collective/policies/{id} → 404 for unknown policy
- GET /v1/collective/installed/{tenant} → returns empty list when nothing installed
- POST /v1/collective/policies/{id}/install → installs successfully (Redis mocked)
- POST /v1/collective/policies/nonexistent/install → 404
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("AION_ADMIN_KEY", "test-admin-key:admin")
os.environ.setdefault("AION_FAIL_MODE", "open")

AUTH = {"Authorization": "Bearer test-admin-key"}


@pytest.fixture
async def client():
    from aion.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Browse ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_browse_returns_six_editorial_policies(client):
    resp = await client.get("/v1/collective/policies", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 6
    assert data["phase"] == "editorial"
    ids = [p["id"] for p in data["policies"]]
    assert "aion-anti-jailbreak-v3" in ids
    assert "aion-lgpd-redaction-v2" in ids


@pytest.mark.asyncio
async def test_browse_sector_filter(client):
    resp = await client.get("/v1/collective/policies?sector=healthcare", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    # Only aion-phi-healthcare-v1 is healthcare-only
    assert data["count"] >= 1
    for policy in data["policies"]:
        assert "healthcare" in [s.lower() for s in policy["sectors"]]


# ── Detail ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_known_policy_returns_provenance(client):
    resp = await client.get("/v1/collective/policies/aion-lgpd-redaction-v2", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "aion-lgpd-redaction-v2"
    assert data["provenance"]["signed_by_aion"] is True
    assert data["provenance"]["author"] == "AION Editorial"
    assert len(data["provenance"]["changelog"]) > 0
    assert data["metrics"]["installs_production"] > 0


@pytest.mark.asyncio
async def test_get_unknown_policy_returns_404(client):
    resp = await client.get("/v1/collective/policies/nonexistent-policy-xyz", headers=AUTH)
    assert resp.status_code == 404


# ── Installed ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_installed_returns_empty_list_when_nothing_installed(client):
    with patch("aion.routers.collective._get_all_installs", new_callable=AsyncMock) as mock_installs:
        mock_installs.return_value = []
        resp = await client.get("/v1/collective/installed/test-tenant", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant"] == "test-tenant"
    assert data["count"] == 0
    assert data["installed"] == []


# ── Install ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_install_known_policy_succeeds(client):
    with (
        patch("aion.routers.collective._get_install_status", new_callable=AsyncMock) as mock_status,
        patch("aion.routers.collective._write_install", new_callable=AsyncMock) as mock_write,
    ):
        mock_status.return_value = None   # not yet installed
        mock_write.return_value = None

        resp = await client.post(
            "/v1/collective/policies/aion-smalltalk-bypass-v2/install",
            headers={**AUTH, "X-Aion-Actor-Reason": "Testing installation in sandbox"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sandbox"
    assert data["policy_id"] == "aion-smalltalk-bypass-v2"


@pytest.mark.asyncio
async def test_install_unknown_policy_returns_404(client):
    resp = await client.post(
        "/v1/collective/policies/no-such-policy/install",
        headers={**AUTH, "X-Aion-Actor-Reason": "Test"},
    )
    assert resp.status_code == 404
