"""Unit tests for aion.shared.economics_daily_job."""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aion.shared.economics_daily_job import (
    _PAGE_SIZE,
    _aggregate,
    _discover_tenants,
    fetch_daily_economics,
    run_economics_daily_sweep,
)


# ── _aggregate ────────────────────────────────────────────────────────────────


def test_aggregate_empty_rows():
    result = _aggregate([])
    assert result["total_requests"] == 0
    assert result["total_cost_usd"] == 0.0
    assert result["total_savings_usd"] == 0.0
    assert result["bypass_count"] == 0
    assert result["block_count"] == 0
    assert result["tokens_saved"] == 0
    assert result["by_model"] == {}


def test_aggregate_single_passthrough_row():
    rows = [
        {
            "decision": "passthrough",
            "model_used": "gpt-4o",
            "cost_actual": "0.005",
            "cost_default": "0.010",
            "tokens_saved": "0",
            "cache_hit": False,
        }
    ]
    result = _aggregate(rows)
    assert result["total_requests"] == 1
    assert result["total_cost_usd"] == pytest.approx(0.005, abs=1e-7)
    assert result["total_savings_usd"] == pytest.approx(0.005, abs=1e-7)
    assert result["bypass_count"] == 0
    assert result["block_count"] == 0
    assert result["by_model"]["gpt-4o"]["requests"] == 1
    assert result["by_model"]["gpt-4o"]["cost_usd"] == pytest.approx(0.005, abs=1e-7)


def test_aggregate_bypass_and_block_counts():
    rows = [
        {"decision": "bypass", "model_used": "gpt-4o-mini", "cost_actual": "0.001",
         "cost_default": "0.002", "tokens_saved": "100"},
        {"decision": "BYPASS", "model_used": "gpt-4o-mini", "cost_actual": "0.001",
         "cost_default": "0.002", "tokens_saved": "80"},
        {"decision": "block", "model_used": "gpt-4o-mini", "cost_actual": "0.000",
         "cost_default": "0.002", "tokens_saved": "0"},
        {"decision": "passthrough", "model_used": "gpt-4o", "cost_actual": "0.010",
         "cost_default": "0.010", "tokens_saved": "0"},
    ]
    result = _aggregate(rows)
    assert result["total_requests"] == 4
    assert result["bypass_count"] == 2
    assert result["block_count"] == 1
    assert result["tokens_saved"] == 180


def test_aggregate_by_model_accumulation():
    rows = [
        {"decision": "passthrough", "model_used": "gpt-4o", "cost_actual": "0.010",
         "cost_default": "0.010", "tokens_saved": "0"},
        {"decision": "passthrough", "model_used": "gpt-4o", "cost_actual": "0.020",
         "cost_default": "0.020", "tokens_saved": "0"},
        {"decision": "passthrough", "model_used": "gpt-4o-mini", "cost_actual": "0.001",
         "cost_default": "0.005", "tokens_saved": "50"},
    ]
    result = _aggregate(rows)
    assert result["by_model"]["gpt-4o"]["requests"] == 2
    assert result["by_model"]["gpt-4o"]["cost_usd"] == pytest.approx(0.03, abs=1e-7)
    assert result["by_model"]["gpt-4o-mini"]["requests"] == 1
    assert result["by_model"]["gpt-4o-mini"]["cost_usd"] == pytest.approx(0.001, abs=1e-7)


def test_aggregate_savings_not_negative():
    """cost_actual > cost_default should not produce negative savings."""
    rows = [
        {"decision": "passthrough", "model_used": "gpt-4o", "cost_actual": "0.020",
         "cost_default": "0.010", "tokens_saved": "0"},
    ]
    result = _aggregate(rows)
    # max(0, cost_default - cost_actual) = max(0, -0.01) = 0
    assert result["total_savings_usd"] == 0.0


def test_aggregate_null_fields_treated_as_zero():
    rows = [
        {"decision": None, "model_used": None, "cost_actual": None,
         "cost_default": None, "tokens_saved": None},
    ]
    result = _aggregate(rows)
    assert result["total_requests"] == 1
    assert result["total_cost_usd"] == 0.0
    assert result["by_model"]["unknown"]["requests"] == 1


def test_aggregate_rounding():
    """Totals should be rounded to 6 decimal places."""
    rows = [
        {"decision": "passthrough", "model_used": "gpt-4o", "cost_actual": "0.0000001",
         "cost_default": "0.0000002", "tokens_saved": "0"},
    ] * 7
    result = _aggregate(rows)
    # 7 * 0.0000001 = 0.0000007 — rounds to 6 decimal places
    assert result["total_cost_usd"] == round(7 * 0.0000001, 6)


# ── run_economics_daily_sweep — no Supabase ───────────────────────────────────


@pytest.mark.asyncio
async def test_run_sweep_skipped_when_supabase_not_configured(monkeypatch):
    monkeypatch.delenv("AION_SUPABASE_URL", raising=False)
    monkeypatch.delenv("AION_SUPABASE_SERVICE_ROLE_KEY", raising=False)
    result = await run_economics_daily_sweep()
    assert result.get("skipped") is True
    assert "supabase_not_configured" in result.get("reason", "")


@pytest.mark.asyncio
async def test_run_sweep_skipped_when_only_url_set(monkeypatch):
    monkeypatch.setenv("AION_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("AION_SUPABASE_SERVICE_ROLE_KEY", raising=False)
    result = await run_economics_daily_sweep()
    assert result.get("skipped") is True


@pytest.mark.asyncio
async def test_run_sweep_returns_summary_on_success(monkeypatch):
    monkeypatch.setenv("AION_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("AION_SUPABASE_SERVICE_ROLE_KEY", "test-key")

    tenant = "acme"
    today = date.today()
    decision_rows = [
        {"decision": "bypass", "model_used": "gpt-4o-mini", "cost_actual": 0.001,
         "cost_default": 0.005, "tokens_saved": 100, "cache_hit": False},
        {"decision": "passthrough", "model_used": "gpt-4o", "cost_actual": 0.010,
         "cost_default": 0.010, "tokens_saved": 0, "cache_hit": False},
    ]

    # Mock httpx.AsyncClient
    mock_resp_tenants = MagicMock()
    mock_resp_tenants.status_code = 200
    mock_resp_tenants.json = MagicMock(return_value=[{"tenant": tenant}])

    mock_resp_decisions = MagicMock()
    mock_resp_decisions.status_code = 200
    mock_resp_decisions.json = MagicMock(return_value=decision_rows)

    mock_resp_upsert = MagicMock()
    mock_resp_upsert.status_code = 201

    mock_client = AsyncMock()
    # First GET: _discover_tenants
    # Next GETs: _fetch_decisions_for_date (3 days × 1 page each)
    # POST: _upsert_daily_row (only days with rows)
    mock_client.get = AsyncMock(side_effect=[
        mock_resp_tenants,          # discover_tenants
        mock_resp_decisions,        # day 0 (today) — has rows
        MagicMock(status_code=200, json=MagicMock(return_value=[])),  # day 1 — empty
        MagicMock(status_code=200, json=MagicMock(return_value=[])),  # day 2 — empty
    ])
    mock_client.post = AsyncMock(return_value=mock_resp_upsert)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await run_economics_daily_sweep()

    assert result["rows_written"] == 1
    assert result["days_processed"] == 1
    assert tenant in result["tenants"]


# ── run_economics_daily_sweep — error handling ────────────────────────────────


@pytest.mark.asyncio
async def test_run_sweep_returns_partial_summary_on_http_error(monkeypatch):
    """Sweep swallows Supabase errors and returns whatever was written before failure."""
    monkeypatch.setenv("AION_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("AION_SUPABASE_SERVICE_ROLE_KEY", "test-key")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("network error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        # Must not raise
        result = await run_economics_daily_sweep()

    assert isinstance(result, dict)
    # Either completed partially or failed — but never raised
    assert "rows_written" in result or "skipped" in result


# ── _discover_tenants pagination ─────────────────────────────────────────────


def _make_tenant_page(tenants: list[str], pad_to: int = 0) -> list[dict]:
    """Build a page of aion_decisions rows with only the tenant field."""
    rows = [{"tenant": t} for t in tenants]
    # Pad with repeated first tenant to hit _PAGE_SIZE without adding new tenants
    if pad_to > len(rows):
        rows += [{"tenant": tenants[0]}] * (pad_to - len(rows))
    return rows


@pytest.mark.asyncio
async def test_discover_tenants_paginates_beyond_first_page(monkeypatch):
    """Tenants that appear only after the first page are discovered correctly."""
    monkeypatch.setenv("AION_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("AION_SUPABASE_SERVICE_ROLE_KEY", "test-key")

    # Page 1 — full page, contains only tenant-A
    page1 = _make_tenant_page(["tenant-A"], pad_to=_PAGE_SIZE)
    # Page 2 — partial page, contains tenant-B (new) + tenant-A (known)
    page2 = [{"tenant": "tenant-B"}, {"tenant": "tenant-A"}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[
        MagicMock(status_code=200, json=MagicMock(return_value=page1)),
        MagicMock(status_code=200, json=MagicMock(return_value=page2)),
    ])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        tenants = await _discover_tenants(mock_client, date.today())

    assert "tenant-A" in tenants
    assert "tenant-B" in tenants
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_discover_tenants_early_exit_when_no_new_tenants(monkeypatch):
    """Stops after a full page that adds zero new tenants (early-exit optimisation)."""
    monkeypatch.setenv("AION_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("AION_SUPABASE_SERVICE_ROLE_KEY", "test-key")

    # Page 1 — full page, tenant-A only
    page1 = _make_tenant_page(["tenant-A"], pad_to=_PAGE_SIZE)
    # Page 2 — would also be a full page with only known tenant-A
    page2 = _make_tenant_page(["tenant-A"], pad_to=_PAGE_SIZE)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[
        MagicMock(status_code=200, json=MagicMock(return_value=page1)),
        MagicMock(status_code=200, json=MagicMock(return_value=page2)),
    ])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        tenants = await _discover_tenants(mock_client, date.today())

    assert tenants == ["tenant-A"]
    # Must stop after page 2 (early exit) — must NOT fetch a third page
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_discover_tenants_stops_on_partial_page(monkeypatch):
    """Returns tenants from a partial (last) page without fetching another."""
    monkeypatch.setenv("AION_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("AION_SUPABASE_SERVICE_ROLE_KEY", "test-key")

    partial_page = [{"tenant": "tenant-X"}, {"tenant": "tenant-Y"}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=
        MagicMock(status_code=200, json=MagicMock(return_value=partial_page))
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        tenants = await _discover_tenants(mock_client, date.today())

    assert set(tenants) == {"tenant-X", "tenant-Y"}
    assert mock_client.get.call_count == 1  # partial page → no second fetch


@pytest.mark.asyncio
async def test_discover_tenants_returns_empty_on_error(monkeypatch):
    """Returns empty list when Supabase returns non-200."""
    monkeypatch.setenv("AION_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("AION_SUPABASE_SERVICE_ROLE_KEY", "test-key")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=MagicMock(status_code=500))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        tenants = await _discover_tenants(mock_client, date.today())

    assert tenants == []


# ── fetch_daily_economics ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_daily_economics_returns_empty_when_no_supabase(monkeypatch):
    monkeypatch.delenv("AION_SUPABASE_URL", raising=False)
    monkeypatch.delenv("AION_SUPABASE_SERVICE_ROLE_KEY", raising=False)
    rows = await fetch_daily_economics("acme", days=30)
    assert rows == []


@pytest.mark.asyncio
async def test_fetch_daily_economics_returns_empty_on_http_error(monkeypatch):
    monkeypatch.setenv("AION_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("AION_SUPABASE_SERVICE_ROLE_KEY", "test-key")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        rows = await fetch_daily_economics("acme", days=30)

    assert rows == []


@pytest.mark.asyncio
async def test_fetch_daily_economics_returns_rows_on_success(monkeypatch):
    monkeypatch.setenv("AION_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("AION_SUPABASE_SERVICE_ROLE_KEY", "test-key")

    mock_rows = [
        {"id": "acme:2025-05-12", "tenant": "acme", "date": "2025-05-12",
         "total_requests": 50, "total_cost_usd": 0.25, "total_savings_usd": 0.10,
         "bypass_count": 10, "block_count": 2, "tokens_saved": 500,
         "by_model": {"gpt-4o": {"requests": 40, "cost_usd": 0.25}},
         "updated_at": "2025-05-12T12:00:00Z"},
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value=mock_rows)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        rows = await fetch_daily_economics("acme", days=30)

    assert len(rows) == 1
    assert rows[0]["date"] == "2025-05-12"
    assert rows[0]["total_cost_usd"] == 0.25


@pytest.mark.asyncio
async def test_fetch_daily_economics_returns_empty_on_non_200(monkeypatch):
    monkeypatch.setenv("AION_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("AION_SUPABASE_SERVICE_ROLE_KEY", "test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 403

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        rows = await fetch_daily_economics("acme", days=30)

    assert rows == []


# ── /v1/economics/daily endpoint ─────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    """FastAPI test client with license and Supabase bypassed."""
    from unittest.mock import MagicMock
    from aion.license import LicenseState
    mock_lic = MagicMock()
    mock_lic.state = LicenseState.ACTIVE
    monkeypatch.setattr("aion.license.validate_license_or_abort", lambda: mock_lic)
    # No Supabase — endpoint should return empty rows gracefully
    monkeypatch.delenv("AION_SUPABASE_URL", raising=False)
    monkeypatch.delenv("AION_SUPABASE_SERVICE_ROLE_KEY", raising=False)
    import aion.config
    aion.config._settings = None
    from fastapi.testclient import TestClient
    import aion.main as main_mod
    with TestClient(main_mod.app, raise_server_exceptions=False) as c:
        yield c


def test_economics_daily_endpoint_returns_200(client):
    resp = client.get("/v1/economics/daily", headers={"X-Aion-Tenant": "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert "rows" in body
    assert isinstance(body["rows"], list)
    assert body["days"] == 30


def test_economics_daily_endpoint_custom_days(client):
    resp = client.get("/v1/economics/daily?days=7", headers={"X-Aion-Tenant": "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 7


def test_economics_daily_endpoint_clamps_days(client):
    """days > 365 should be clamped to 365."""
    resp = client.get("/v1/economics/daily?days=9999", headers={"X-Aion-Tenant": "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 365


def test_economics_daily_endpoint_clamps_days_min(client):
    """days < 1 should be clamped to 1."""
    resp = client.get("/v1/economics/daily?days=0", headers={"X-Aion-Tenant": "acme"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 1
