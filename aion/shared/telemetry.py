"""Telemetry — event emission for AION decisions.

Events are stored locally (bounded deque) and optionally forwarded to ARGOS async.
Business signals are tracked as counters for Prometheus export.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import Any, Optional

import httpx

from aion.config import get_settings

logger = logging.getLogger("aion.telemetry")

# Bounded buffer — never grows beyond MAX_BUFFER (Track 0)
_MAX_BUFFER = 10_000
_event_buffer: deque[dict[str, Any]] = deque(maxlen=_MAX_BUFFER)

# Singleton httpx client for ARGOS forwarding (Track 0 — no new client per event)
_argos_client: Optional[httpx.AsyncClient] = None

# Business signal counters (Track B)
_counters: dict[str, int] = {
    "requests_total": 0,
    "bypass_total": 0,
    "block_total": 0,
    "passthrough_total": 0,
    "fallback_total": 0,
    "errors_total": 0,
    "tokens_saved_total": 0,
}
_cost_saved_total: float = 0.0
_latency_samples: deque[float] = deque(maxlen=1000)

# Metadata whitelist — only these fields are safe to persist (Track E)
_SAFE_METADATA_KEYS = {
    "module_latencies",
    "complexity_score",
    "route_reason",
    "safe_mode",
    "skipped_modules",
    "failed_modules",
    "detected_intent",
    "intent_confidence",
}


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Remove potentially sensitive fields from metadata before storage."""
    return {k: v for k, v in metadata.items() if k in _SAFE_METADATA_KEYS}


def _get_argos_client() -> httpx.AsyncClient:
    global _argos_client
    if _argos_client is None:
        _argos_client = httpx.AsyncClient(
            timeout=5.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _argos_client


async def shutdown_telemetry() -> None:
    global _argos_client
    if _argos_client:
        await _argos_client.aclose()
        _argos_client = None


class TelemetryEvent:
    """Standard AION telemetry event."""

    def __init__(
        self,
        event_type: str,
        module: str,
        request_id: str,
        *,
        decision: str = "",
        model_used: str = "",
        tokens_saved: int = 0,
        cost_saved: float = 0.0,
        latency_ms: float = 0.0,
        tenant: str = "default",
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.data = {
            "schema_version": "1.0",
            "event_type": event_type,
            "module": module,
            "request_id": request_id,
            "decision": decision,
            "model_used": model_used,
            "tokens_saved": tokens_saved,
            "cost_saved": cost_saved,
            "latency_ms": latency_ms,
            "tenant": tenant,
            "timestamp": time.time(),
            "metadata": _sanitize_metadata(metadata) if metadata else {},
        }


async def emit(event: TelemetryEvent) -> None:
    """Emit telemetry event — bounded buffer + counters + optional ARGOS forward."""
    _event_buffer.append(event.data)

    # Update business signal counters
    _counters["requests_total"] += 1
    decision = event.data.get("decision", "")
    if decision == "bypass":
        _counters["bypass_total"] += 1
    elif decision == "block":
        _counters["block_total"] += 1
    else:
        _counters["passthrough_total"] += 1

    tokens_saved = event.data.get("tokens_saved", 0)
    if tokens_saved > 0:
        _counters["tokens_saved_total"] += tokens_saved

    global _cost_saved_total
    cost_saved = event.data.get("cost_saved", 0.0)
    if cost_saved > 0:
        _cost_saved_total += cost_saved

    latency = event.data.get("latency_ms", 0.0)
    if latency > 0:
        _latency_samples.append(latency)

    if event.data.get("metadata", {}).get("failed_modules"):
        _counters["fallback_total"] += 1

    logger.debug("telemetry: %s", json.dumps(event.data, default=str))

    # Forward to ARGOS (async, non-blocking, reusing client)
    settings = get_settings()
    if settings.argos_telemetry_url:
        try:
            client = _get_argos_client()
            await client.post(settings.argos_telemetry_url, json=event.data)
        except Exception:
            logger.warning("Failed to forward telemetry to ARGOS", exc_info=False)


def get_recent_events(limit: int = 100, tenant: Optional[str] = None) -> list[dict[str, Any]]:
    """Get recent telemetry events from bounded buffer."""
    events = list(_event_buffer)
    if tenant:
        events = [e for e in events if e.get("tenant") == tenant]
    return events[-limit:]


def get_stats(tenant: Optional[str] = None) -> dict[str, Any]:
    """Compute aggregate stats from buffer."""
    events = list(_event_buffer)
    if tenant:
        events = [e for e in events if e.get("tenant") == tenant]

    if not events:
        return {"total_events": 0}

    bypasses = sum(1 for e in events if e["decision"] == "bypass")
    blocks = sum(1 for e in events if e["decision"] == "block")

    return {
        "total_events": len(events),
        "bypasses": bypasses,
        "blocks": blocks,
        "passthroughs": len(events) - bypasses - blocks,
        "bypass_rate": bypasses / len(events) if events else 0,
        "total_tokens_saved": sum(e.get("tokens_saved", 0) for e in events),
        "total_cost_saved": round(sum(e.get("cost_saved", 0.0) for e in events), 6),
        "avg_latency_ms": round(
            sum(e.get("latency_ms", 0) for e in events) / len(events), 2
        ),
    }


def get_counters() -> dict[str, Any]:
    """Get business signal counters for Prometheus export."""
    result = dict(_counters)
    result["cost_saved_total"] = round(_cost_saved_total, 6)

    # Latency percentiles
    if _latency_samples:
        sorted_samples = sorted(_latency_samples)
        n = len(sorted_samples)
        result["latency_p50_ms"] = round(sorted_samples[int(n * 0.5)], 2)
        result["latency_p95_ms"] = round(sorted_samples[int(n * 0.95)], 2)
        result["latency_p99_ms"] = round(sorted_samples[min(int(n * 0.99), n - 1)], 2)

    result["buffer_size"] = len(_event_buffer)
    return result


def reset_counters() -> None:
    """Reset counters (for testing)."""
    global _cost_saved_total
    for k in _counters:
        _counters[k] = 0
    _cost_saved_total = 0.0
    _latency_samples.clear()
    _event_buffer.clear()
