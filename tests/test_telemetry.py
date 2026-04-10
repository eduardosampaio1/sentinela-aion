"""Tests for telemetry system."""

import pytest

from aion.shared.telemetry import TelemetryEvent, emit, get_recent_events, get_stats, _event_buffer


@pytest.fixture(autouse=True)
def clear_buffer():
    _event_buffer.clear()
    yield
    _event_buffer.clear()


@pytest.mark.asyncio
async def test_emit_event():
    event = TelemetryEvent(
        event_type="bypass",
        module="estixe",
        request_id="test-123",
        decision="bypass",
        tokens_saved=100,
    )
    await emit(event)
    events = get_recent_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "bypass"
    assert events[0]["tokens_saved"] == 100


@pytest.mark.asyncio
async def test_get_stats():
    for i in range(5):
        await emit(TelemetryEvent(
            event_type="bypass",
            module="estixe",
            request_id=f"bypass-{i}",
            decision="bypass",
            tokens_saved=50,
            latency_ms=10.0,
        ))
    for i in range(3):
        await emit(TelemetryEvent(
            event_type="passthrough",
            module="pipeline",
            request_id=f"pass-{i}",
            decision="passthrough",
            latency_ms=5.0,
        ))

    stats = get_stats()
    assert stats["total_events"] == 8
    assert stats["bypasses"] == 5
    assert stats["passthroughs"] == 3
    assert stats["total_tokens_saved"] == 250
    assert stats["bypass_rate"] == 5 / 8


@pytest.mark.asyncio
async def test_tenant_filtering():
    await emit(TelemetryEvent(
        event_type="bypass", module="estixe", request_id="t1",
        decision="bypass", tenant="acme",
    ))
    await emit(TelemetryEvent(
        event_type="bypass", module="estixe", request_id="t2",
        decision="bypass", tenant="globex",
    ))

    acme_events = get_recent_events(tenant="acme")
    assert len(acme_events) == 1
    assert acme_events[0]["tenant"] == "acme"

    acme_stats = get_stats(tenant="acme")
    assert acme_stats["total_events"] == 1
