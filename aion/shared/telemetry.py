"""Telemetry — event emission for AION decisions.

Events are stored locally (bounded deque) and optionally forwarded to ARGOS async.
Business signals are tracked as counters for Prometheus export.

F-06: user message text is NEVER persisted in raw form. The `input` field of an
event is always a sanitized dict (`_sanitize_input`), never the original string.
This is a hard product promise ("nothing leaves the customer's environment except
metadata"); the binary must guarantee it regardless of operator configuration.
"""

from __future__ import annotations

import hashlib
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
    # Existing pipeline signals
    "module_latencies",
    "complexity_score",
    "route_reason",
    "safe_mode",
    "skipped_modules",
    "failed_modules",
    "detected_intent",
    "intent_confidence",
    # ESTIXE — velocity (rolling-window brute-force detection)
    "velocity_alert",
    "velocity_recent_blocks",
    # ESTIXE — shadow mode (categoria em observacao, nao bloqueia)
    "shadow_risk_category",
    "shadow_risk_level",
    "shadow_risk_confidence",
    "shadow_risk_matched_seed",
    # ESTIXE — flagged (risk_level=medium, FLAG + CONTINUE)
    "flagged_risk_category",
    "flagged_risk_confidence",
    "flagged_risk_matched_seed",
    "flagged_risk_source",
    # ESTIXE — detected (bloqueou)
    "detected_risk_category",
    "risk_level",
    "risk_confidence",
    "risk_matched_seed",
    "risk_threshold_used",
    "risk_source",
    # ESTIXE — output guard
    "output_risk_category",
    "output_risk_confidence",
    "output_stream_blocked",
    "output_stream_pii_sanitized",
    # ESTIXE — PII (counts/types only; raw content excluido por _sanitize)
    "pii_violations",
    "pii_audited",
    # Cache tier — origem da decisão (auditoria de cache hit vs pipeline fresh)
    # Crítico: falso negativo cacheado propaga-se; auditores precisam identificar
    # se um CONTINUE veio do pipeline ou do cache para rastrear a decisão original.
    "decision_source",   # "cache" | "pipeline"
}


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Remove potentially sensitive fields from metadata before storage."""
    return {k: v for k, v in metadata.items() if k in _SAFE_METADATA_KEYS}


# F-06: input must be one of these dict keys, never raw text.
# Schema bumped to "1.1" so downstream consumers can detect the new shape.
_SANITIZED_INPUT_VERSION = "1.1"


def _sanitize_input(text: str) -> dict[str, Any]:
    """Reduce a user message to non-recoverable metadata.

    The output is intentionally lossy: a full SHA-256 hash (for cross-event
    correlation / dedup) plus length and an ASCII-printable preview prefix
    (first 8 chars, which is unlikely to contain a complete piece of PII —
    e.g. "Olá, tu" reveals nothing operationally useful but lets engineers
    tell apart "user said hi" from "user pasted a 500-char prompt").

    NEVER include the full raw text. NEVER include the last 8 chars (those
    are more likely to contain identifiers like "@example.com" tails).
    """
    if not text:
        return {
            "schema": _SANITIZED_INPUT_VERSION,
            "length": 0,
            "hash": None,
            "preview": "",
        }
    raw = str(text)
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    # 8-char preview from the start, ASCII-only, no control chars.
    preview = "".join(ch for ch in raw[:8] if ch.isprintable() and ord(ch) < 128)
    return {
        "schema": _SANITIZED_INPUT_VERSION,
        "length": len(raw),
        "hash": digest,
        "preview": preview,
    }


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
        input_text: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ):
        # F-33: environment and policy_version for traceability across deployments.
        import os as _os
        _environment = _os.environ.get("AION_PROFILE", "development")
        _aion_version = _os.environ.get("AION_VERSION", "unknown")

        self.data = {
            "schema_version": "1.2",  # F-33: added environment, aion_version
            "event_type": event_type,
            "module": module,
            "request_id": request_id,
            "decision": decision,
            "model_used": model_used,
            "tokens_saved": tokens_saved,
            "cost_saved": cost_saved,
            "latency_ms": latency_ms,
            "response_time_ms": round(latency_ms),   # alias para o console
            "environment": _environment,
            "aion_version": _aion_version,
            "tenant": tenant,
            # F-06: never store raw user text. `input` is a small dict with
            # length/hash/preview only — the original text is unrecoverable
            # from telemetry, so /v1/events, /v1/explain, and ARGOS forward
            # never leak prompt content.
            "input": _sanitize_input(input_text),
            "timestamp": time.time(),
            "metadata": _sanitize_metadata(metadata) if metadata else {},
        }


async def emit(event: TelemetryEvent) -> None:
    """Emit telemetry event — bounded buffer + counters + optional ARGOS forward.

    Com Redis disponível, também grava em lista Redis compartilhada entre replicas
    (aion:events) com TTL. Permite /v1/events retornar eventos de QUALQUER replica,
    não só do processo local.

    F-07: cost_saved_total e tokens_saved_total são persistidos em Redis
    (`aion:counters:global`) com TTL longa para sobreviver a restarts e
    apresentar métricas históricas duráveis em /v1/economics e dashboards.

    F-10: cada evento também é gravado em `aion:explain:{request_id}` (TTL
    = telemetry_retention_hours) para que /v1/explain consiga reconstruir
    decisões muito além do buffer in-memory.
    """
    # Annotate com replica_id para visibilidade
    import os
    replica_id = os.environ.get("AION_REPLICA_ID", "local")
    event.data.setdefault("replica", replica_id)

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

    # Cross-replica: grava em lista Redis compartilhada (fire-and-forget)
    await _redis_emit(event.data)

    # F-07: persist durable counters (fire-and-forget; counter survives restarts).
    # F-10: persist per-request explain payload (fire-and-forget; TTL bounded).
    await _redis_persist_counters_delta(
        requests=1,
        bypass=1 if decision == "bypass" else 0,
        block=1 if decision == "block" else 0,
        passthrough=1 if decision not in ("bypass", "block") else 0,
        tokens_saved=tokens_saved if tokens_saved > 0 else 0,
        cost_saved=cost_saved if cost_saved > 0 else 0.0,
        fallback=1 if event.data.get("metadata", {}).get("failed_modules") else 0,
    )
    await _redis_persist_explain(event.data)

    # Forward to ARGOS (async, non-blocking, reusing client)
    settings = get_settings()
    if settings.argos_telemetry_url:
        try:
            client = _get_argos_client()
            await client.post(settings.argos_telemetry_url, json=event.data)
        except Exception:
            logger.warning("Failed to forward telemetry to ARGOS", exc_info=False)


# ── Redis-backed cross-replica event store ──
_redis_client_events = None
_redis_last_failure_events: float = 0.0
_redis_retry_interval_events: float = 10.0


async def _get_events_redis():
    """Lazy Redis client com circuit breaker. No-op quando REDIS_URL nao setado ou Redis down."""
    global _redis_client_events, _redis_last_failure_events
    import time
    if _redis_last_failure_events > 0 and (time.time() - _redis_last_failure_events) < _redis_retry_interval_events:
        return None
    if _redis_client_events is not None:
        return _redis_client_events
    import os
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return None
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(
            url, decode_responses=True,
            socket_timeout=1.0, socket_connect_timeout=1.0,
        )
        await client.ping()
        _redis_client_events = client
        _redis_last_failure_events = 0.0
        logger.info("Events telemetry: Redis-backed cross-replica store enabled")
    except Exception as e:
        _redis_last_failure_events = time.time()
        logger.info("Events telemetry: Redis unavailable (%s) — local-only por %.0fs",
                    type(e).__name__, _redis_retry_interval_events)
    return _redis_client_events


def _mark_events_redis_failure():
    global _redis_client_events, _redis_last_failure_events
    import time
    _redis_last_failure_events = time.time()
    _redis_client_events = None


async def _redis_emit(event_data: dict) -> None:
    """Fire-and-forget: grava evento na lista Redis. No-op se Redis indisponivel."""
    r = await _get_events_redis()
    if r is None:
        return
    try:
        key = "aion:events"
        await r.lpush(key, json.dumps(event_data, default=str))
        await r.ltrim(key, 0, _MAX_BUFFER - 1)  # Mantém max N eventos
        await r.expire(key, 86400)  # 24h TTL
    except Exception as e:
        _mark_events_redis_failure()
        logger.debug("Redis event write failed: %s", e)


# ── F-07: durable counters (Redis-backed, surviving restarts) ────────────────
_COUNTERS_REDIS_KEY = "aion:counters:global"
_COUNTERS_TTL_SECONDS = 30 * 86400  # 30 days
_counters_loaded_from_redis = False


async def _redis_persist_counters_delta(
    *,
    requests: int = 0,
    bypass: int = 0,
    block: int = 0,
    passthrough: int = 0,
    fallback: int = 0,
    tokens_saved: int = 0,
    cost_saved: float = 0.0,
) -> None:
    """Increment durable counters in Redis. Fire-and-forget, no-op if Redis down.

    Cost is stored as integer micro-USD (×1_000_000) to use HINCRBY atomically.
    Reader divides back. Avoids floating-point drift across many small deltas.
    """
    r = await _get_events_redis()
    if r is None:
        return
    try:
        pipe = r.pipeline()
        if requests:
            pipe.hincrby(_COUNTERS_REDIS_KEY, "requests_total", requests)
        if bypass:
            pipe.hincrby(_COUNTERS_REDIS_KEY, "bypass_total", bypass)
        if block:
            pipe.hincrby(_COUNTERS_REDIS_KEY, "block_total", block)
        if passthrough:
            pipe.hincrby(_COUNTERS_REDIS_KEY, "passthrough_total", passthrough)
        if fallback:
            pipe.hincrby(_COUNTERS_REDIS_KEY, "fallback_total", fallback)
        if tokens_saved:
            pipe.hincrby(_COUNTERS_REDIS_KEY, "tokens_saved_total", tokens_saved)
        if cost_saved > 0:
            # store cost in micro-USD (×1e6) for atomic integer ops
            pipe.hincrby(_COUNTERS_REDIS_KEY, "cost_saved_micro_usd", int(round(cost_saved * 1_000_000)))
        pipe.expire(_COUNTERS_REDIS_KEY, _COUNTERS_TTL_SECONDS)
        await pipe.execute()
    except Exception as e:
        _mark_events_redis_failure()
        logger.debug("Redis counter persist failed: %s", e)


async def load_persistent_counters() -> bool:
    """Restore counters from Redis at boot. Idempotent; only loads once.

    Called from main.lifespan after Redis comes online. If Redis is missing
    or empty, in-memory counters keep their (zero) defaults.
    Returns True if state was loaded, False otherwise.
    """
    global _counters_loaded_from_redis, _cost_saved_total
    if _counters_loaded_from_redis:
        return False
    r = await _get_events_redis()
    if r is None:
        return False
    try:
        raw = await r.hgetall(_COUNTERS_REDIS_KEY)
        if not raw:
            _counters_loaded_from_redis = True
            return False
        for k in ("requests_total", "bypass_total", "block_total", "passthrough_total",
                  "fallback_total", "tokens_saved_total"):
            if k in raw:
                try:
                    _counters[k] = int(raw[k])
                except (TypeError, ValueError):
                    pass
        if "cost_saved_micro_usd" in raw:
            try:
                _cost_saved_total = int(raw["cost_saved_micro_usd"]) / 1_000_000
            except (TypeError, ValueError):
                pass
        _counters_loaded_from_redis = True
        logger.info(
            "Telemetry counters restored from Redis: requests=%d bypass=%d block=%d cost_saved=$%.4f",
            _counters.get("requests_total", 0),
            _counters.get("bypass_total", 0),
            _counters.get("block_total", 0),
            _cost_saved_total,
        )
        return True
    except Exception as e:
        logger.debug("Redis counter load failed: %s", e)
        return False


# ── F-10: durable explain store (per-request payload with TTL) ───────────────
_EXPLAIN_KEY_PREFIX = "aion:explain:"


async def _redis_persist_explain(event_data: dict) -> None:
    """Store the event payload under aion:explain:{request_id} for /v1/explain.

    TTL = settings.telemetry_retention_hours (default 168h = 7 days). Operators
    can extend this via env for longer audit retention.
    """
    request_id = event_data.get("request_id")
    if not request_id:
        return
    r = await _get_events_redis()
    if r is None:
        return
    try:
        settings = get_settings()
        ttl_seconds = max(60, int(getattr(settings, "telemetry_retention_hours", 168)) * 3600)
        key = f"{_EXPLAIN_KEY_PREFIX}{request_id}"
        await r.set(key, json.dumps(event_data, default=str), ex=ttl_seconds)
    except Exception as e:
        _mark_events_redis_failure()
        logger.debug("Redis explain persist failed: %s", e)


async def lookup_explain(request_id: str, tenant: Optional[str] = None) -> Optional[dict]:
    """Find a single request's explain payload from durable Redis store.

    Falls back to None if Redis is unavailable or the key is gone (TTL expired).
    Caller (/v1/explain) should also check the in-memory buffer as final fallback.
    """
    if not request_id:
        return None
    r = await _get_events_redis()
    if r is None:
        return None
    try:
        raw = await r.get(f"{_EXPLAIN_KEY_PREFIX}{request_id}")
        if not raw:
            return None
        ev = json.loads(raw)
        if tenant and ev.get("tenant") != tenant:
            return None
        return ev
    except Exception as e:
        _mark_events_redis_failure()
        logger.debug("Redis explain lookup failed: %s", e)
        return None


async def get_recent_events_redis(limit: int = 100, tenant: Optional[str] = None) -> list[dict]:
    """Busca eventos no Redis (cross-replica). Fallback pra local se Redis down."""
    r = await _get_events_redis()
    if r is None:
        return get_recent_events(limit, tenant)
    try:
        raw = await r.lrange("aion:events", 0, limit * 3)  # fetch mais pra filtrar por tenant
        events = []
        for item in raw:
            try:
                ev = json.loads(item)
                if tenant and ev.get("tenant") != tenant:
                    continue
                events.append(ev)
                if len(events) >= limit:
                    break
            except Exception:
                continue
        return events
    except Exception as e:
        _mark_events_redis_failure()
        logger.warning("Redis event read failed, fallback local: %s", e)
        return get_recent_events(limit, tenant)


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


async def beacon_shadow_stats(tenant: str, stats: dict) -> None:
    """Emit anonymized shadow calibration stats to ARGOS (fire-and-forget).

    SHADOW MODE ONLY — disabled by default.
    This function is a no-op unless ARGOS_TELEMETRY_URL is explicitly configured.
    During POC deployments, ARGOS_TELEMETRY_URL is unset and nothing is sent.

    When enabled (opt-in Shadow Mode with customer DPA):
    - Sends only aggregate signals — no user content, no prompts, no PII.
    - Payload: {type, tenant, categories: [{category, total_seen, avg_confidence, days_monitored}]}
    - Purpose: calibration signal for risk_taxonomy.yaml improvements.
    """
    settings = get_settings()
    if not settings.argos_telemetry_url:
        return

    if not stats:
        return

    payload = {
        "type": "shadow_calibration_beacon",
        "tenant": tenant,
        "timestamp": time.time(),
        "categories": [
            {
                "category": cat,
                "total_seen": obs.get("total_seen", 0) if isinstance(obs, dict) else getattr(obs, "total_seen", 0),
                "avg_confidence": obs.get("avg_confidence", 0.0) if isinstance(obs, dict) else round(getattr(obs, "avg_confidence", 0.0), 4),
                "days_monitored": obs.get("days_monitored", 0.0) if isinstance(obs, dict) else round(getattr(obs, "days_monitored", 0.0), 2),
                "promoted": obs.get("promoted", False) if isinstance(obs, dict) else getattr(obs, "promoted", False),
            }
            for cat, obs in stats.items()
        ],
    }

    try:
        client = _get_argos_client()
        await client.post(settings.argos_telemetry_url, json=payload)
    except Exception:
        logger.debug("Shadow beacon to ARGOS failed (non-critical)")
