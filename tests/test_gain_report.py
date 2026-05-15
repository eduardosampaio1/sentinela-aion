"""Tests for AION Gain Report — builder unit tests + route-level tests."""

from __future__ import annotations

import datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════

_NOW = datetime.datetime(2026, 5, 5, 12, 0, 0)
_30D_AGO = _NOW - datetime.timedelta(days=30)
_TENANT = "acme"


def _make_econ_bucket(
    total_requests: int = 200,
    total_savings: float = 0.75,
    bypass_count: int = 100,
    model: str = "gpt-4o-mini",
    savings_vs_default: float = 0.45,
) -> str:
    bucket = {
        "summary": {
            "total_requests": total_requests,
            "total_actual_cost": 0.25,
            "total_default_cost": 1.0,
            "total_savings": total_savings,
            "savings_percentage": 75.0,
        },
        "by_model": {
            model: {
                "requests": total_requests // 2,
                "cost": 0.05,
                "savings_vs_default": savings_vs_default,
                "avg_latency_ms": 320.0,
            }
        },
        "by_intent": {},
        "by_decision": {"bypass": bypass_count, "continue": total_requests - bypass_count},
    }
    return json.dumps(bucket)


def _make_redis_mock(econ_json: str | None = None) -> AsyncMock:
    r = AsyncMock()
    r.ping = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=econ_json)
    r.scan = AsyncMock(return_value=(0, []))
    return r


# ═══════════════════════════════════════════
# Builder unit tests
# ═══════════════════════════════════════════


@pytest.mark.asyncio
async def test_gain_bypass_events():
    """bypass count and cost avoided come from economics bucket."""
    econ = _make_econ_bucket(total_requests=300, total_savings=1.5, bypass_count=150)
    r = _make_redis_mock(econ_json=econ)

    with patch("aion.nemos.gain_report._redis", AsyncMock(return_value=r)):
        from aion.nemos.gain_report import GainReportBuilder
        report = await GainReportBuilder().build(_TENANT, _30D_AGO, _NOW)

    assert report.llm_calls_avoided >= 150
    assert report.estimated_cost_avoided_usd > 0.0
    assert "economics_bucket" in report.data_sources
    assert report.total_requests >= 300


@pytest.mark.asyncio
async def test_gain_tokens_saved_from_metis_only():
    """tokens_saved comes from METIS only; telemetry counter is not added on top."""
    metis_data = json.dumps({
        "tokens_saved": 42_000,
        "total": 80,
        "compression_effectiveness": {"value": 0.3},
        "avg_tokens_saved": {"value": 525.0},
    })

    r = _make_redis_mock(econ_json=_make_econ_bucket())

    async def _get_side_effect(key: str):
        if "metis" in key and "optimization" in key:
            return metis_data
        return _make_econ_bucket()

    r.get = AsyncMock(side_effect=_get_side_effect)

    with patch("aion.nemos.gain_report._redis", AsyncMock(return_value=r)):
        from aion.nemos.gain_report import GainReportBuilder
        report = await GainReportBuilder().build(_TENANT, _30D_AGO, _NOW)

    assert report.tokens_saved == 42_000
    assert "metis_optimization" in report.data_sources
    # Verify telemetry counter was NOT summed on top
    notes = " ".join(report.calculation_notes)
    assert "METIS optimization only" in notes


@pytest.mark.asyncio
async def test_gain_model_substitution():
    """top_models sorted by cost_avoided_usd descending."""
    bucket = {
        "summary": {
            "total_requests": 500,
            "total_actual_cost": 0.5,
            "total_default_cost": 2.0,
            "total_savings": 1.5,
            "savings_percentage": 75.0,
        },
        "by_model": {
            "gpt-4o-mini": {"requests": 300, "cost": 0.3, "savings_vs_default": 1.2, "avg_latency_ms": 300.0},
            "claude-haiku": {"requests": 200, "cost": 0.2, "savings_vs_default": 0.3, "avg_latency_ms": 250.0},
        },
        "by_intent": {},
        "by_decision": {"bypass": 100, "continue": 400},
    }
    r = _make_redis_mock(econ_json=json.dumps(bucket))

    with patch("aion.nemos.gain_report._redis", AsyncMock(return_value=r)):
        from aion.nemos.gain_report import GainReportBuilder
        report = await GainReportBuilder().build(_TENANT, _30D_AGO, _NOW)

    assert len(report.top_models) >= 2
    # Should be sorted descending by cost_avoided_usd
    savings = [m.cost_avoided_usd for m in report.top_models]
    assert savings == sorted(savings, reverse=True)
    assert report.top_models[0].model_used == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_gain_empty_data():
    """No Redis data → all zeros, confidence=low, limitations non-empty, data_sources=[]."""
    r = _make_redis_mock(econ_json=None)

    with (
        patch("aion.nemos.gain_report._redis", AsyncMock(return_value=r)),
        patch("aion.shared.telemetry.get_counters", return_value={
            "bypass_total": 0,
            "requests_total": 0,
            "cost_saved_total": 0.0,
            "tokens_saved_total": 0,
        }),
    ):
        from aion.nemos.gain_report import GainReportBuilder
        report = await GainReportBuilder().build(_TENANT, _30D_AGO, _NOW)

    assert report.total_requests == 0
    assert report.llm_calls_avoided == 0
    assert report.estimated_cost_avoided_usd == 0.0
    assert report.tokens_saved == 0
    assert report.confidence == "low"
    assert len(report.limitations) >= 1
    d = report.to_dict()
    assert isinstance(d["limitations"], list)
    assert d["summary"]["total_requests"] == 0


@pytest.mark.asyncio
async def test_gain_confidence_low_below_threshold():
    """5 requests in a single day, none for other days → confidence stays 'low'."""
    today_str = _NOW.date().isoformat()
    econ_today = _make_econ_bucket(total_requests=5, total_savings=0.01, bypass_count=2)

    r = _make_redis_mock(econ_json=None)  # default: no data

    async def _get_side_effect(key: str):
        # Only return data for today's bucket; all other days return None
        if f":daily:{today_str}" in key:
            return econ_today
        return None

    r.get = AsyncMock(side_effect=_get_side_effect)

    with (
        patch("aion.nemos.gain_report._redis", AsyncMock(return_value=r)),
        patch("aion.shared.telemetry.get_counters", return_value={
            "bypass_total": 0, "requests_total": 0, "cost_saved_total": 0.0, "tokens_saved_total": 0,
        }),
    ):
        from aion.nemos.gain_report import GainReportBuilder
        report = await GainReportBuilder().build(_TENANT, _30D_AGO, _NOW)

    assert report.confidence == "low"
    assert any("20" in lim for lim in report.limitations)


@pytest.mark.asyncio
async def test_gain_serialization():
    """to_dict() produces valid JSON with all required top-level keys."""
    econ = _make_econ_bucket()
    r = _make_redis_mock(econ_json=econ)

    with patch("aion.nemos.gain_report._redis", AsyncMock(return_value=r)):
        from aion.nemos.gain_report import GainReportBuilder
        report = await GainReportBuilder().build(_TENANT, _30D_AGO, _NOW)

    d = report.to_dict()
    # Must be JSON-serializable
    raw = json.dumps(d)
    parsed = json.loads(raw)

    # Required top-level keys
    for key in ("schema_version", "summary", "breakdowns", "confidence",
                 "limitations", "data_sources", "calculation_notes", "generated_at"):
        assert key in parsed, f"Missing key: {key}"

    # Required summary keys
    summary = parsed["summary"]
    for key in ("total_requests", "llm_calls_avoided", "llm_calls_avoided_pct",
                 "tokens_saved", "estimated_cost_avoided_usd", "estimated_latency_avoided_ms"):
        assert key in summary, f"Missing summary key: {key}"

    # Breakdowns
    breakdowns = parsed["breakdowns"]
    for key in ("top_saving_drivers", "top_intents", "top_models", "top_strategies"):
        assert key in breakdowns, f"Missing breakdown key: {key}"

    assert parsed["schema_version"] == "1.0"
    assert isinstance(parsed["limitations"], list)
    assert isinstance(parsed["data_sources"], list)
    assert isinstance(parsed["calculation_notes"], list)


# ═══════════════════════════════════════════
# Route-level tests
# ═══════════════════════════════════════════


@pytest.fixture
def client():
    from aion.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_gain_route_returns_200(client):
    """GET /v1/nemos/gain returns 200 with valid JSON structure."""
    from aion.nemos.gain_report import AionGainReport, GainReportBuilder

    fake_report = AionGainReport(
        schema_version="1.0",
        window_start="2026-04-05T00:00:00Z",
        window_end="2026-05-05T00:00:00Z",
        total_requests=150,
        llm_calls_avoided=80,
        llm_calls_avoided_pct=0.533,
        tokens_saved=5000,
        estimated_cost_avoided_usd=0.42,
        estimated_latency_avoided_ms=62400,
        confidence="medium",
        limitations=[],
        data_sources=["economics_bucket"],
        calculation_notes=["estimated_cost_avoided from economics_bucket"],
        generated_at="2026-05-05T12:00:00Z",
    )

    with patch.object(GainReportBuilder, "build", AsyncMock(return_value=fake_report)):
        response = client.get(
            "/v1/nemos/gain",
            headers={"X-Aion-Tenant": "acme"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["schema_version"] == "1.0"
    assert "summary" in data
    assert "breakdowns" in data


def test_gain_route_tenant_from_header(client):
    """Tenant is resolved from X-Aion-Tenant header, not workspace_id param."""
    from aion.nemos.gain_report import AionGainReport, GainReportBuilder

    captured_tenant: list[str] = []

    async def _capture_build(self, tenant, from_dt, to_dt):
        captured_tenant.append(tenant)
        return AionGainReport(
            schema_version="1.0",
            window_start=from_dt.isoformat() + "Z",
            window_end=to_dt.isoformat() + "Z",
            total_requests=0, llm_calls_avoided=0, llm_calls_avoided_pct=0.0,
            tokens_saved=0, estimated_cost_avoided_usd=0.0, estimated_latency_avoided_ms=0,
            confidence="low", limitations=[], data_sources=[], calculation_notes=[],
            generated_at="2026-05-05T12:00:00Z",
        )

    with patch.object(GainReportBuilder, "build", _capture_build):
        client.get(
            "/v1/nemos/gain?workspace_id=should-be-ignored",
            headers={"X-Aion-Tenant": "header-tenant"},
        )

    assert captured_tenant == ["header-tenant"]


def test_gain_route_invalid_dates_returns_400(client):
    """Malformed 'from' or 'to' params return HTTP 400."""
    response = client.get(
        "/v1/nemos/gain?from=notadate&to=alsonotadate",
        headers={"X-Aion-Tenant": "acme"},
    )
    assert response.status_code == 400
    detail = response.json()
    assert "detail" in detail
    # Either 'from' or 'to' appears in the detail depending on parse order
    assert "Invalid date format" in detail["detail"]


def test_gain_route_reversed_dates_returns_400(client):
    """'from' after 'to' returns HTTP 400."""
    response = client.get(
        "/v1/nemos/gain?from=2026-05-05&to=2026-04-01",
        headers={"X-Aion-Tenant": "acme"},
    )
    assert response.status_code == 400
    assert "'from' must be before 'to'" in response.json()["detail"]


def test_gain_route_group_by_adds_note(client):
    """group_by param is accepted and adds a calculation_note."""
    from aion.nemos.gain_report import AionGainReport, GainReportBuilder

    fake_report = AionGainReport(
        schema_version="1.0",
        window_start="2026-04-05T00:00:00Z",
        window_end="2026-05-05T00:00:00Z",
        total_requests=0, llm_calls_avoided=0, llm_calls_avoided_pct=0.0,
        tokens_saved=0, estimated_cost_avoided_usd=0.0, estimated_latency_avoided_ms=0,
        confidence="low", limitations=[], data_sources=[], calculation_notes=[],
        generated_at="2026-05-05T12:00:00Z",
    )

    with patch.object(GainReportBuilder, "build", AsyncMock(return_value=fake_report)):
        response = client.get(
            "/v1/nemos/gain?group_by=intent",
            headers={"X-Aion-Tenant": "acme"},
        )

    assert response.status_code == 200
    notes = response.json().get("calculation_notes", [])
    assert any("group_by" in n for n in notes)


# ═══════════════════════════════════════════
# Additional builder tests (T1, T3, T4)
# ═══════════════════════════════════════════


@pytest.mark.asyncio
async def test_gain_tokens_saved_telemetry_fallback():
    """When METIS key is absent, tokens_saved falls back to telemetry counter."""
    r = _make_redis_mock(econ_json=_make_econ_bucket())
    # r.get returns econ bucket for all keys — METIS key will parse as econ bucket
    # but 'tokens_saved' won't be in it, so tokens_saved stays 0 → triggers fallback.
    # Simpler: make METIS key return None explicitly.
    async def _get_side_effect(key: str):
        if "metis" in key:
            return None
        return _make_econ_bucket()

    r.get = AsyncMock(side_effect=_get_side_effect)

    with (
        patch("aion.nemos.gain_report._redis", AsyncMock(return_value=r)),
        patch("aion.shared.telemetry.get_counters", return_value={
            "bypass_total": 0, "requests_total": 0, "cost_saved_total": 0.0,
            "tokens_saved_total": 8_000,
        }),
    ):
        from aion.nemos.gain_report import GainReportBuilder
        report = await GainReportBuilder().build(_TENANT, _30D_AGO, _NOW)

    assert report.tokens_saved == 8_000
    assert "metis_optimization" not in report.data_sources
    assert any("telemetry counter" in n for n in report.calculation_notes)
    assert any("METIS" in lim for lim in report.limitations)


@pytest.mark.asyncio
async def test_gain_intent_from_events():
    """Intent breakdown aggregates windowed events grouped by detected_intent."""
    import calendar as _cal

    event_ts = float(_cal.timegm(_NOW.timetuple())) - 3600  # 1 hour before _NOW

    events = [
        {"decision": "bypass", "cost_saved": 0.10, "timestamp": event_ts,
         "tenant": _TENANT, "metadata": {"detected_intent": "saldo", "decision_source": "policy"}},
        {"decision": "bypass", "cost_saved": 0.05, "timestamp": event_ts,
         "tenant": _TENANT, "metadata": {"detected_intent": "saldo", "decision_source": "policy"}},
        {"decision": "passthrough", "cost_saved": 0.0, "timestamp": event_ts,
         "tenant": _TENANT, "metadata": {"detected_intent": "saldo", "decision_source": "policy"}},
        {"decision": "bypass", "cost_saved": 0.20, "timestamp": event_ts,
         "tenant": _TENANT, "metadata": {"detected_intent": "horario", "decision_source": "cache"}},
    ]

    r = _make_redis_mock(econ_json=_make_econ_bucket(total_requests=300))

    with (
        patch("aion.nemos.gain_report._redis", AsyncMock(return_value=r)),
        patch("aion.shared.telemetry.get_recent_events_redis", AsyncMock(return_value=events)),
    ):
        from aion.nemos.gain_report import GainReportBuilder
        report = await GainReportBuilder().build(_TENANT, _30D_AGO, _NOW)

    # Should be sorted by cost_avoided desc → horario first
    assert len(report.top_intents) == 2
    assert report.top_intents[0].intent == "horario"
    assert abs(report.top_intents[0].cost_avoided_usd - 0.20) < 0.001

    saldo = next(i for i in report.top_intents if i.intent == "saldo")
    assert saldo.calls_avoided == 2
    assert abs(saldo.cost_avoided_usd - 0.15) < 0.001
    assert abs(saldo.bypass_accuracy - 2 / 3) < 0.01
    assert saldo.source == "events"


@pytest.mark.asyncio
async def test_gain_strategy_cache_vs_policy():
    """Strategy breakdown correctly splits cache_hit vs policy_bypass events."""
    import calendar as _cal

    event_ts = float(_cal.timegm(_NOW.timetuple())) - 3600

    events = [
        {"decision": "bypass", "cost_saved": 0.20, "timestamp": event_ts,
         "tenant": _TENANT, "metadata": {"detected_intent": "", "decision_source": "cache"}},
        {"decision": "bypass", "cost_saved": 0.10, "timestamp": event_ts,
         "tenant": _TENANT, "metadata": {"detected_intent": "", "decision_source": "policy"}},
        {"decision": "bypass", "cost_saved": 0.05, "timestamp": event_ts,
         "tenant": _TENANT, "metadata": {"detected_intent": "", "decision_source": "policy"}},
    ]

    r = _make_redis_mock(econ_json=_make_econ_bucket(total_requests=200))

    with (
        patch("aion.nemos.gain_report._redis", AsyncMock(return_value=r)),
        patch("aion.shared.telemetry.get_recent_events_redis", AsyncMock(return_value=events)),
    ):
        from aion.nemos.gain_report import GainReportBuilder
        report = await GainReportBuilder().build(_TENANT, _30D_AGO, _NOW)

    strategies = {s.strategy: s for s in report.top_strategies}
    assert strategies["cache_hit"].count == 1
    assert abs(strategies["cache_hit"].cost_avoided_usd - 0.20) < 0.001
    assert strategies["policy_bypass"].count == 2
    assert abs(strategies["policy_bypass"].cost_avoided_usd - 0.15) < 0.001
