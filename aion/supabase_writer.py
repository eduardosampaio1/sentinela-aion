"""AION → Supabase writer (fire-and-forget).

Writes decision records and audit events to Supabase via PostgREST.

Configuration (env vars):
  AION_SUPABASE_URL             — e.g. https://vtyckndcjczxqcqacsby.supabase.co
  AION_SUPABASE_SERVICE_ROLE_KEY — service role JWT (select + insert only)

If either var is unset, all writes are no-ops with zero overhead.
Circuit breaker: after one failure, retries are paused for 30 s to avoid
blocking request processing or filling logs.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("aion.supabase_writer")

_URL: str = ""
_KEY: str = ""
_client: Optional[Any] = None  # httpx.AsyncClient — lazy init
_enabled: Optional[bool] = None  # None = not yet checked
_last_failure: float = 0.0
_RETRY_SECONDS: float = 30.0


def _is_enabled() -> bool:
    global _URL, _KEY, _enabled
    if _enabled is None:
        _URL = os.environ.get("AION_SUPABASE_URL", "").rstrip("/")
        _KEY = os.environ.get("AION_SUPABASE_SERVICE_ROLE_KEY", "")
        _enabled = bool(_URL and _KEY)
        if _enabled:
            logger.info("Supabase writer enabled → %s", _URL)
    return _enabled


def _get_client():
    global _client
    if _client is None:
        import httpx
        _client = httpx.AsyncClient(
            timeout=5.0,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
            headers={
                "apikey": _KEY,
                "Authorization": f"Bearer {_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
    return _client


async def _post(table: str, payload: dict) -> None:
    """POST one row to PostgREST. Swallows all errors (fire-and-forget)."""
    global _last_failure
    now = time.time()
    if _last_failure > 0 and (now - _last_failure) < _RETRY_SECONDS:
        return
    try:
        client = _get_client()
        resp = await client.post(f"{_URL}/rest/v1/{table}", json=payload)
        if resp.status_code not in (200, 201, 204):
            logger.debug("Supabase %s write failed: %s — %s", table, resp.status_code, resp.text[:200])
            _last_failure = now
        else:
            _last_failure = 0.0  # reset circuit breaker on success
    except Exception as exc:
        _last_failure = now
        logger.debug("Supabase %s write error: %s", table, exc)


async def write_decision(
    *,
    tenant: str,
    request_id: str,
    decision: str,
    model_used: str = "",
    detected_intent: str = "",
    complexity_score: float = 0.0,
    risk_category: str = "",
    tokens_input: int = 0,
    tokens_output: int = 0,
    cost_actual: float = 0.0,
    cost_default: float = 0.0,
    tokens_saved: int = 0,
    cost_saved: float = 0.0,
    pii_detected: bool = False,
    pii_count: int = 0,
    latency_ms: float = 0.0,
    estixe_decision: str = "",
    nomos_decision: str = "",
    metis_decision: str = "",
    cache_hit: bool = False,
    safe_mode: bool = False,
    metadata: Optional[dict] = None,
) -> None:
    """Write one decision row to aion_decisions. No-op when Supabase is not configured."""
    if not _is_enabled():
        return
    row: dict = {
        "tenant": tenant,
        "request_id": request_id or None,
        "decision": decision,
        "model_used": model_used or None,
        "detected_intent": detected_intent or None,
        "complexity_score": float(complexity_score) if complexity_score else None,
        "risk_category": risk_category or None,
        "tokens_input": tokens_input or None,
        "tokens_output": tokens_output or None,
        "cost_actual": float(cost_actual) if cost_actual else None,
        "cost_default": float(cost_default) if cost_default else None,
        "tokens_saved": tokens_saved or None,
        "cost_saved": float(cost_saved) if cost_saved else None,
        "pii_detected": pii_detected,
        "pii_count": pii_count,
        "latency_ms": int(latency_ms) if latency_ms else None,
        "estixe_decision": estixe_decision or None,
        "nomos_decision": nomos_decision or None,
        "metis_decision": metis_decision or None,
        "cache_hit": cache_hit,
        "safe_mode": safe_mode,
        "metadata": metadata,
    }
    await _post("aion_decisions", row)


async def write_audit_event(
    *,
    tenant: str,
    event_type: str,
    actor: str = "",
    target: str = "",
    outcome: str = "ok",
    request_id: str = "",
    event_hash: str = "",
    prev_hash: str = "",
    details: Optional[dict] = None,
) -> None:
    """Write one audit event row to aion_audit_events. No-op when Supabase is not configured."""
    if not _is_enabled():
        return
    row: dict = {
        "tenant": tenant,
        "event_type": event_type,
        "actor": actor or None,
        "target": target or None,
        "outcome": outcome or None,
        "request_id": request_id or None,
        "event_hash": event_hash or None,
        "prev_hash": prev_hash or None,
        "details": details,
    }
    await _post("aion_audit_events", row)


async def shutdown() -> None:
    """Close the httpx client. Called from app shutdown."""
    global _client
    if _client:
        await _client.aclose()
        _client = None
