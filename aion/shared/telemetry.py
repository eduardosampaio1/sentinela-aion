"""Telemetry — event emission for AION decisions.

Events are stored locally and optionally forwarded to ARGOS async.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import httpx

from aion.config import get_settings

logger = logging.getLogger("aion.telemetry")

# In-memory buffer for local telemetry (last N events)
_event_buffer: list[dict[str, Any]] = []
_MAX_BUFFER = 10_000


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
            "metadata": metadata or {},
        }


async def emit(event: TelemetryEvent) -> None:
    """Emit telemetry event — local buffer + optional ARGOS forward."""
    global _event_buffer

    _event_buffer.append(event.data)
    if len(_event_buffer) > _MAX_BUFFER:
        _event_buffer = _event_buffer[-_MAX_BUFFER:]

    logger.debug("telemetry: %s", json.dumps(event.data, default=str))

    settings = get_settings()
    if settings.argos_telemetry_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    settings.argos_telemetry_url,
                    json=event.data,
                )
        except Exception:
            logger.warning("Failed to forward telemetry to ARGOS", exc_info=False)


def get_recent_events(limit: int = 100, tenant: Optional[str] = None) -> list[dict[str, Any]]:
    """Get recent telemetry events from local buffer."""
    events = _event_buffer
    if tenant:
        events = [e for e in events if e.get("tenant") == tenant]
    return events[-limit:]


def get_stats(tenant: Optional[str] = None) -> dict[str, Any]:
    """Compute aggregate stats from local buffer."""
    events = _event_buffer
    if tenant:
        events = [e for e in events if e.get("tenant") == tenant]

    if not events:
        return {"total_events": 0}

    bypasses = [e for e in events if e["decision"] == "bypass"]
    blocks = [e for e in events if e["decision"] == "block"]
    total_tokens_saved = sum(e.get("tokens_saved", 0) for e in events)
    total_cost_saved = sum(e.get("cost_saved", 0.0) for e in events)

    return {
        "total_events": len(events),
        "bypasses": len(bypasses),
        "blocks": len(blocks),
        "passthroughs": len(events) - len(bypasses) - len(blocks),
        "bypass_rate": len(bypasses) / len(events) if events else 0,
        "total_tokens_saved": total_tokens_saved,
        "total_cost_saved": round(total_cost_saved, 6),
        "avg_latency_ms": round(
            sum(e.get("latency_ms", 0) for e in events) / len(events), 2
        ),
    }
