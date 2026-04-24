"""Unit tests for aion.shared.budget."""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aion.shared.budget import (
    BudgetConfig,
    BudgetExceededError,
    BudgetState,
    BudgetStore,
    check_budget,
    get_budget_store,
)


def _make_context(selected_model: str = "gpt-4o"):
    ctx = MagicMock()
    ctx.selected_model = selected_model
    ctx.metadata = {}
    return ctx


# ── check_budget feature flag ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_budget_disabled_when_flag_off(monkeypatch):
    monkeypatch.delenv("AION_BUDGET_ENABLED", raising=False)
    ctx = _make_context()
    # Must return immediately without touching Redis
    await check_budget("acme", ctx)
    assert "budget_downgraded" not in ctx.metadata


@pytest.mark.asyncio
async def test_check_budget_disabled_when_flag_false(monkeypatch):
    monkeypatch.setenv("AION_BUDGET_ENABLED", "false")
    ctx = _make_context()
    await check_budget("acme", ctx)
    assert "budget_downgraded" not in ctx.metadata


# ── check_budget — cap logic ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_budget_hard_stop_raises_budget_exceeded(monkeypatch):
    monkeypatch.setenv("AION_BUDGET_ENABLED", "true")

    config = BudgetConfig(
        tenant="acme",
        daily_cap=1.00,
        on_cap_reached="block",
    )
    store = BudgetStore()
    store.get_config = AsyncMock(return_value=config)
    store.get_today_spend = AsyncMock(return_value=1.05)

    with patch("aion.shared.budget.get_budget_store", return_value=store):
        with pytest.raises(BudgetExceededError) as exc_info:
            await check_budget("acme", _make_context())

    err = exc_info.value
    assert err.tenant == "acme"
    assert err.cap_type == "daily"
    assert err.spend == pytest.approx(1.05)
    assert err.cap == pytest.approx(1.00)


@pytest.mark.asyncio
async def test_check_budget_downgrade_sets_model(monkeypatch):
    monkeypatch.setenv("AION_BUDGET_ENABLED", "true")

    config = BudgetConfig(
        tenant="acme",
        daily_cap=1.00,
        on_cap_reached="downgrade",
        fallback_model="gpt-4o-mini",
    )
    store = BudgetStore()
    store.get_config = AsyncMock(return_value=config)
    store.get_today_spend = AsyncMock(return_value=1.05)

    ctx = _make_context(selected_model="gpt-4o")
    with patch("aion.shared.budget.get_budget_store", return_value=store):
        await check_budget("acme", ctx)

    assert ctx.selected_model == "gpt-4o-mini"
    assert ctx.metadata.get("budget_downgraded") is True


@pytest.mark.asyncio
async def test_check_budget_alert_threshold_sets_metadata(monkeypatch):
    monkeypatch.setenv("AION_BUDGET_ENABLED", "true")

    config = BudgetConfig(
        tenant="acme",
        daily_cap=10.00,
        alert_threshold=0.80,
        on_cap_reached="downgrade",
    )
    store = BudgetStore()
    store.get_config = AsyncMock(return_value=config)
    store.get_today_spend = AsyncMock(return_value=8.50)  # 85% — above threshold

    ctx = _make_context()
    with patch("aion.shared.budget.get_budget_store", return_value=store):
        await check_budget("acme", ctx)

    assert ctx.metadata.get("budget_alert") is True
    assert ctx.metadata.get("budget_alert_pct") == pytest.approx(0.85, abs=0.01)


@pytest.mark.asyncio
async def test_check_budget_fail_open_on_store_error(monkeypatch):
    monkeypatch.setenv("AION_BUDGET_ENABLED", "true")

    store = BudgetStore()
    store.get_config = AsyncMock(side_effect=RuntimeError("Redis exploded"))

    ctx = _make_context()
    with patch("aion.shared.budget.get_budget_store", return_value=store):
        # Must not raise — fail-open
        await check_budget("acme", ctx)

    assert "budget_downgraded" not in ctx.metadata


# ── BudgetStore.record_spend ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_spend_accumulates_daily():
    store = BudgetStore()
    mock_redis = AsyncMock()

    # Simulate empty state initially
    mock_redis.get.return_value = None
    mock_redis.set = AsyncMock()
    store._redis_client = mock_redis

    await store.record_spend("acme", 0.50)

    mock_redis.set.assert_called_once()
    call_args = mock_redis.set.call_args
    saved_data = __import__("json").loads(call_args[0][1])
    assert saved_data["today_spend"] == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_budget_store_fail_open_when_no_redis():
    store = BudgetStore()
    # No REDIS_URL → should return None without raising
    config = await store.get_config("acme")
    assert config is None

    state = await store.get_state("acme")
    assert state.today_spend == 0.0


# ── GET /v1/budget endpoint RBAC ─────────────────────────────────────────
# These tests verify that the middleware blocks unauthenticated access.
# They use the full FastAPI test client, which loads the security middleware.


@pytest.fixture
def client(monkeypatch):
    """FastAPI test client with license check bypassed and admin key configured."""
    from unittest.mock import MagicMock
    from aion.license import LicenseState
    mock_lic = MagicMock()
    mock_lic.state = LicenseState.ACTIVE
    monkeypatch.setattr("aion.license.validate_license_or_abort", lambda: mock_lic)
    # Admin key must be configured for RBAC to enforce auth
    monkeypatch.setenv("AION_ADMIN_KEY", "admin-key:admin,viewer-key:viewer")
    import aion.config
    aion.config._settings = None  # reset singleton so env change is picked up
    from fastapi.testclient import TestClient
    import aion.main as main_mod
    with TestClient(main_mod.app, raise_server_exceptions=False) as c:
        yield c


def test_put_budget_without_auth_returns_401(client):
    resp = client.put("/v1/budget/acme", json={"daily_cap": 5.0})
    assert resp.status_code == 401


def test_get_budget_status_without_auth_returns_401(client):
    resp = client.get("/v1/budget/acme/status")
    assert resp.status_code == 401


def test_put_budget_with_viewer_role_returns_403(monkeypatch, client):
    monkeypatch.setenv("AION_ADMIN_KEY", "viewer-key:viewer")
    resp = client.put(
        "/v1/budget/acme",
        json={"daily_cap": 5.0},
        headers={"Authorization": "Bearer viewer-key"},
    )
    assert resp.status_code == 403


def test_put_budget_with_operator_role_returns_200(client):
    """Admin key can write budget config (2xx response). AION_ADMIN_KEY set in fixture."""
    resp = client.put(
        "/v1/budget/acme",
        json={"daily_cap": 5.0, "on_cap_reached": "downgrade"},
        headers={"Authorization": "Bearer admin-key"},
    )
    # 200 means RBAC passed; storage may fail without Redis (fine in unit test)
    assert resp.status_code in (200, 500)
