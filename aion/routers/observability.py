"""Observability router: health, metrics, stats, events, pipeline, economics, cache, benchmark, etc."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from aion import __version__
from aion.config import get_settings
from aion.middleware import get_in_flight
from aion.shared.telemetry import get_counters, get_recent_events, get_stats

logger = logging.getLogger("aion")

router = APIRouter()


def _get_pipeline():
    import aion.main as _main
    return _main._pipeline


def _get_trust_guard_health() -> dict | None:
    """Load persisted TrustState and return a dict for the /health trust_guard section."""
    try:
        from aion.trust_guard.trust_state import load_trust_state
        import datetime
        state = load_trust_state()

        def _fmt_ts(ts: float) -> str | None:
            if not ts:
                return None
            return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "trust_state": state.trust_state,
            "license_id": state.license_id or None,
            "integrity_status": state.integrity_status,
            "entitlement_valid_until": _fmt_ts(state.entitlement_expires_at),
            "last_heartbeat": _fmt_ts(state.last_heartbeat_at),
            "restricted_features": state.restricted_features,
            "grace_hours_remaining": state.grace_hours_remaining,
            "heartbeat_required": state.heartbeat_required,
        }
    except Exception:
        return None


def _get_pipeline_ready():
    import aion.main as _main
    return _main._pipeline_ready


def _get_cache_summary() -> dict:
    """Get cache summary for economics endpoint."""
    try:
        from aion.cache import get_cache
        cache = get_cache()
        s = cache.stats
        return {
            "enabled": cache.enabled,
            "hits": s.hits,
            "misses": s.misses,
            "hit_rate": round(s.hit_rate, 4),
            "total_entries": s.total_entries,
        }
    except Exception:
        return {"enabled": False, "hits": 0, "misses": 0, "hit_rate": 0, "total_entries": 0}


@router.get("/health", tags=["Observability"])
async def health():
    _pipeline = _get_pipeline()
    _pipeline_ready = _get_pipeline_ready()
    if not _pipeline:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "reason": "pipeline_not_initialized", "ready": False})

    health_data = _pipeline.get_health()
    health_data["version"] = __version__
    health_data["active_modules"] = _pipeline.active_modules
    health_data["requests_in_flight"] = get_in_flight()
    health_data["ready"] = _pipeline_ready.is_set()

    degraded_components = health_data.get("degraded_components", [])
    for _mod in _pipeline._pre_modules:
        if _mod.name == "estixe" and hasattr(_mod, "health"):
            estixe_health = _mod.health
            health_data["estixe"] = estixe_health
            if estixe_health.get("classifier") == "unavailable":
                if "estixe_classifier" not in degraded_components:
                    degraded_components.append("estixe_classifier")
            break

    if degraded_components:
        health_data["degraded_components"] = degraded_components
        if health_data.get("mode") == "normal":
            health_data["mode"] = "degraded"

    # ── Auth pass-through detection ──────────────────────────────────────────
    # When require_chat_auth=True but AION_ADMIN_KEY is not configured,
    # AION silently skips auth validation. This is deliberate fail-open
    # (we never block the client's chat), but it must be visible in health.
    settings = get_settings()
    auth_warnings: list[str] = []
    if settings.require_chat_auth and not (getattr(settings, "admin_key", "") or ""):
        auth_warnings.append(
            "AION_ADMIN_KEY not set — chat auth disabled; operating in pass-through for auth"
        )
        if "auth" not in degraded_components:
            degraded_components.append("auth")
        if health_data.get("mode") == "normal":
            health_data["mode"] = "degraded"

    if not os.environ.get("AION_SESSION_AUDIT_SECRET"):
        auth_warnings.append(
            "AION_SESSION_AUDIT_SECRET not set — audit HMAC signatures are unsigned"
        )

    if auth_warnings:
        health_data["auth_warnings"] = auth_warnings

    health_data["auth_mode"] = (
        "pass_through"
        if (settings.require_chat_auth and not (getattr(settings, "admin_key", "") or ""))
        else "active"
    )
    # ─────────────────────────────────────────────────────────────────────────

    # ── Deployment mode visibility ────────────────────────────────────────────
    # Exposes how AION is configured so the console and operators can see the
    # active mode without inspecting env vars manually.
    aion_mode = settings.mode or "not_configured"
    executes_llm = (
        settings.nomos_enabled
        and bool(settings.default_provider)
        and aion_mode not in ("poc_decision", "decision_only")
    )
    health_data["aion_mode"] = aion_mode
    health_data["executes_llm"] = executes_llm
    health_data["telemetry_enabled"] = bool(settings.argos_telemetry_url)
    health_data["collective_enabled"] = settings.collective_enabled
    # ─────────────────────────────────────────────────────────────────────────

    # ── Trust Guard status ────────────────────────────────────────────────────
    trust_guard_data = _get_trust_guard_health()
    if trust_guard_data:
        health_data["trust_guard"] = trust_guard_data
        # Reflect TAMPERED/INVALID in degraded_components (admin visibility)
        tg_state = trust_guard_data.get("trust_state", "ACTIVE")
        if tg_state in ("TAMPERED", "INVALID") and "trust_guard" not in degraded_components:
            degraded_components.append("trust_guard")
        if tg_state == "RESTRICTED" and "nemos_restricted" not in degraded_components:
            degraded_components.append("nemos_restricted")
    # ─────────────────────────────────────────────────────────────────────────

    mode = health_data.get("mode", "unknown")
    status = 200 if mode == "normal" else 207 if mode in ("degraded", "safe") else 503
    return JSONResponse(status_code=status, content=health_data)


@router.get("/ready", tags=["Observability"])
async def readiness():
    """Kubernetes readiness probe. Returns 200 only when pipeline is fully initialized."""
    _pipeline_ready = _get_pipeline_ready()
    if _pipeline_ready.is_set():
        return {"ready": True}
    return JSONResponse(status_code=503, content={"ready": False})


@router.get("/metrics", tags=["Observability"])
async def metrics():
    """Prometheus-compatible metrics (Track B)."""
    _pipeline = _get_pipeline()
    counters = get_counters()
    lines = []
    lines.append(f'# HELP aion_requests_total Total requests processed')
    lines.append(f'# TYPE aion_requests_total counter')
    lines.append(f'aion_requests_total {counters["requests_total"]}')

    for decision in ("bypass", "block", "passthrough", "fallback"):
        key = f"{decision}_total"
        lines.append(f'aion_decisions_total{{decision="{decision}"}} {counters.get(key, 0)}')

    lines.append(f'aion_errors_total {counters.get("errors_total", 0)}')
    lines.append(f'aion_tokens_saved_total {counters.get("tokens_saved_total", 0)}')
    lines.append(f'aion_cost_saved_total {counters.get("cost_saved_total", 0)}')
    lines.append(f'aion_buffer_size {counters.get("buffer_size", 0)}')
    lines.append(f'aion_requests_in_flight {get_in_flight()}')

    if "latency_p50_ms" in counters:
        lines.append(f'aion_pipeline_latency_ms{{quantile="0.5"}} {counters["latency_p50_ms"]}')
        lines.append(f'aion_pipeline_latency_ms{{quantile="0.95"}} {counters["latency_p95_ms"]}')
        lines.append(f'aion_pipeline_latency_ms{{quantile="0.99"}} {counters["latency_p99_ms"]}')

    replica_id = os.environ.get("AION_REPLICA_ID", "local")
    lines.append(f'# HELP aion_classifier_degraded 1 if embedding classifier unavailable')
    lines.append(f'# TYPE aion_classifier_degraded gauge')
    if _pipeline:
        for mod in _pipeline._pre_modules:
            if mod.name == "estixe":
                health_data = mod.health
                is_degraded = 1 if health_data.get("degraded") else 0
                lines.append(f'aion_classifier_degraded{{replica="{replica_id}"}} {is_degraded}')
                lines.append(f'aion_estixe_risk_categories{{replica="{replica_id}"}} {health_data.get("risk_categories", 0)}')
                lines.append(f'aion_estixe_shadow_categories{{replica="{replica_id}"}} {health_data.get("risk_shadow_categories", 0)}')
                cs = health_data.get("risk_classify_cache", {})
                lines.append(f'aion_classify_cache_size{{replica="{replica_id}"}} {cs.get("size", 0)}')
                lines.append(f'aion_classify_cache_hits_total{{replica="{replica_id}"}} {cs.get("hits", 0)}')
                lines.append(f'aion_classify_cache_misses_total{{replica="{replica_id}"}} {cs.get("misses", 0)}')
                lines.append(f'aion_classify_cache_hit_rate{{replica="{replica_id}"}} {cs.get("hit_rate", 0)}')

                dc = health_data.get("decision_cache", {})
                lines.append(f'# HELP aion_decision_cache_hit_rate Hit rate do cache de decisão do pipeline inteiro')
                lines.append(f'# TYPE aion_decision_cache_hit_rate gauge')
                lines.append(f'aion_decision_cache_size{{replica="{replica_id}"}} {dc.get("size", 0)}')
                lines.append(f'aion_decision_cache_hits_total{{replica="{replica_id}"}} {dc.get("hits", 0)}')
                lines.append(f'aion_decision_cache_misses_total{{replica="{replica_id}"}} {dc.get("misses", 0)}')
                lines.append(f'aion_decision_cache_hit_rate{{replica="{replica_id}"}} {dc.get("hit_rate", 0)}')
                lines.append(f'aion_decision_cache_evictions_total{{replica="{replica_id}"}} {dc.get("evictions", 0)}')

                th = health_data.get("tier_hits", {})
                lines.append(f'# HELP aion_tier_hits_total Decisions taken per tier (hot→cold)')
                lines.append(f'# TYPE aion_tier_hits_total counter')
                for tier, count in th.items():
                    lines.append(f'aion_tier_hits_total{{replica="{replica_id}",tier="{tier}"}} {count}')
                break

    return Response(content="\n".join(lines) + "\n", media_type="text/plain")


@router.get("/v1/stats", tags=["Observability"])
async def stats(request: Request):
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    return get_stats(tenant)


@router.get("/v1/events", tags=["Observability"])
async def events(request: Request, limit: int = 100):
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    tenant_filter = None if tenant == settings.default_tenant else tenant
    from aion.shared.telemetry import get_recent_events_redis
    return await get_recent_events_redis(limit, tenant_filter)


@router.get("/v1/pipeline", tags=["Observability"])
async def pipeline_topology():
    """Retorna a topologia do pipeline: pre-LLM, post-LLM, settings dos modulos."""
    _pipeline = _get_pipeline()
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    settings = get_settings()
    return {
        "pre_llm_modules": [m.name for m in _pipeline._pre_modules],
        "post_llm_modules": [m.name for m in _pipeline._post_modules],
        "module_settings": {
            "estixe_enabled": settings.estixe_enabled,
            "nomos_enabled": settings.nomos_enabled,
            "metis_enabled": settings.metis_enabled,
        },
        "safe_mode": settings.safe_mode,
    }


@router.get("/v1/economics", tags=["Observability"])
async def runtime_economics(request: Request):
    """Runtime economics — visible cost savings and efficiency metrics."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    counters = get_counters()
    stats_data = get_stats(tenant)

    total_requests = counters.get("requests_total", 0)
    bypasses = counters.get("bypass_total", 0)
    tokens_saved = counters.get("tokens_saved_total", 0)
    cost_saved = counters.get("cost_saved_total", 0.0)

    return {
        "tenant": tenant,
        "economics": {
            "total_requests": total_requests,
            "llm_calls_avoided": bypasses,
            "llm_call_avoidance_rate": round(bypasses / total_requests, 4) if total_requests else 0,
            "tokens_saved": tokens_saved,
            "cost_saved_usd": cost_saved,
            "avg_tokens_saved_per_request": round(tokens_saved / total_requests, 1) if total_requests else 0,
        },
        "decisions": {
            "bypasses": bypasses,
            "blocks": counters.get("block_total", 0),
            "passthroughs": counters.get("passthrough_total", 0),
            "fallbacks": counters.get("fallback_total", 0),
        },
        "latency": {
            "p50_ms": counters.get("latency_p50_ms", 0),
            "p95_ms": counters.get("latency_p95_ms", 0),
            "p99_ms": counters.get("latency_p99_ms", 0),
        },
        "cache": _get_cache_summary(),
    }


@router.get("/v1/cache/stats", tags=["Observability"])
async def cache_stats(request: Request):
    """Semantic cache performance metrics."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    try:
        from aion.cache import get_cache
        cache = get_cache()
        stats = cache.stats
        return {
            "enabled": cache.enabled,
            "hits": stats.hits,
            "misses": stats.misses,
            "hit_rate": round(stats.hit_rate, 4),
            "invalidations": stats.invalidations,
            "evictions": stats.evictions,
            "total_entries": stats.total_entries,
            "entries_by_tenant": stats.entries_by_tenant,
        }
    except Exception:
        return {
            "enabled": False,
            "hits": 0,
            "misses": 0,
            "hit_rate": 0,
            "invalidations": 0,
            "evictions": 0,
            "total_entries": 0,
            "entries_by_tenant": {},
        }


@router.get("/v1/benchmark/{tenant_id}", tags=["Observability"])
async def tenant_benchmark(tenant_id: str):
    """Per-tenant operational baseline with trends and module maturity."""
    from aion.nemos import get_nemos
    nemos = get_nemos()
    baseline = await nemos.get_baseline(tenant_id)
    if not baseline:
        return {"tenant": tenant_id, "baseline": None, "message": "No data yet"}

    trends = await nemos.get_baseline_trends(tenant_id)
    maturity = await nemos.get_module_maturity(tenant_id)

    return {
        "tenant": tenant_id,
        "baseline": baseline.to_dict(),
        "trends": trends,
        "module_maturity": maturity,
    }


@router.get("/v1/metrics/tenant/{tenant_id}", tags=["Observability"])
async def tenant_metrics(tenant_id: str):
    """Per-tenant metrics — decisions, savings, latency for a specific tenant."""
    stats_data = get_stats(tenant_id)
    return {
        "tenant": tenant_id,
        "metrics": stats_data,
    }


@router.get("/v1/models", tags=["Observability"])
async def list_models():
    settings = get_settings()
    return {"models": [{"id": settings.default_model, "provider": settings.default_provider, "type": "default"}]}


@router.get("/version", tags=["Observability"])
async def version_info(request: Request):
    """Build and license version info — trust_state, integrity, tenant. Requires operator auth."""
    from aion import __version__
    try:
        from aion.trust_guard.trust_state import load_trust_state
        state = load_trust_state()
        try:
            from aion.trust_guard.license_authority import get_license_claims
            claims = get_license_claims()
            license_tier = claims.get("tier", "")
        except Exception:
            license_tier = ""

        return {
            "aion_version": __version__,
            "build_id": state.build_id or None,
            "tenant_id": state.tenant_id or None,
            "license_id": state.license_id or None,
            "license_tier": license_tier,
            "integrity_status": state.integrity_status,
            "trust_state": state.trust_state,
        }
    except Exception:
        return {
            "aion_version": __version__,
            "build_id": None,
            "tenant_id": None,
            "license_id": None,
            "license_tier": None,
            "integrity_status": "UNVERIFIED",
            "trust_state": "ACTIVE",
        }


@router.get("/v1/recommendations/{tenant_id}", tags=["Observability"])
async def tenant_recommendations(tenant_id: str):
    """AI-generated recommendations for optimizing a tenant's AI operations."""
    from aion.nemos import get_nemos
    recs = await get_nemos().get_recommendations(tenant_id)
    return {
        "tenant": tenant_id,
        "recommendations": [r.to_dict() for r in recs],
        "count": len(recs),
    }


@router.get("/v1/explain/{request_id}", tags=["Observability"])
async def explain_decision(request_id: str, request: Request):
    """Explainability — full trace of what AION decided for a specific request.

    F-10: prioriza store durável (Redis com TTL = telemetry_retention_hours).
    Fallback para buffer in-memory só quando Redis indisponível ou chave expirou.
    """
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    # 1. Durable store (Redis): sobrevive a restarts e cobre janela de retention.
    from aion.shared.telemetry import lookup_explain
    durable = await lookup_explain(request_id, tenant=tenant)
    if durable is not None:
        return {
            "request_id": request_id,
            "tenant": tenant,
            "found": True,
            "source": "durable",
            "decision": durable.get("decision"),
            "model_used": durable.get("model_used"),
            "module": durable.get("module"),
            "tokens_saved": durable.get("tokens_saved", 0),
            "cost_saved": durable.get("cost_saved", 0.0),
            "latency_ms": durable.get("latency_ms", 0.0),
            "metadata": durable.get("metadata", {}),
            "input_summary": durable.get("input"),  # F-06 sanitized dict, never raw text
            "timestamp": durable.get("timestamp"),
        }

    # 2. Fallback: in-memory buffer (current process only, last ~10k events).
    events = get_recent_events(limit=1000, tenant=tenant)
    for event in events:
        if event.get("request_id") == request_id:
            return {
                "request_id": request_id,
                "tenant": tenant,
                "found": True,
                "source": "memory",
                "decision": event.get("decision"),
                "model_used": event.get("model_used"),
                "module": event.get("module"),
                "tokens_saved": event.get("tokens_saved", 0),
                "cost_saved": event.get("cost_saved", 0.0),
                "latency_ms": event.get("latency_ms", 0.0),
                "metadata": event.get("metadata", {}),
                "input_summary": event.get("input"),
                "timestamp": event.get("timestamp"),
            }

    return {
        "request_id": request_id,
        "found": False,
        "message": (
            "Request not found in durable store or recent events. "
            "If you expect this request to be auditable, ensure REDIS_URL is configured "
            "and AION_TELEMETRY_RETENTION_HOURS covers the lookback window."
        ),
    }
