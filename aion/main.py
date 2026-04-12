"""AION — Motor Realtime do Sentinela.

FastAPI application serving as an OpenAI-compatible proxy gateway.
Modes: Normal | Degraded | Safe (SAFE_MODE)
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from aion import __version__
from aion.config import FailMode, get_settings
from aion.middleware import AionSecurityMiddleware, get_audit_log, get_in_flight
from aion.pipeline import Pipeline, build_pipeline
from aion.proxy import (
    build_bypass_stream,
    forward_request,
    forward_request_stream,
    shutdown_client,
)
from aion.shared.schemas import (
    ChatCompletionRequest,
    Decision,
    PipelineContext,
)
from aion.shared.telemetry import (
    get_counters,
    get_recent_events,
    get_stats,
    reset_counters,
    shutdown_telemetry,
)

logger = logging.getLogger("aion")

# --- Global state ---
_pipeline: Pipeline | None = None

# Streaming timeout (seconds)
_STREAM_TIMEOUT = 300


def _error_response(status: int, message: str, code: str, error_type: str = "api_error") -> JSONResponse:
    """OpenAI-compatible error response format."""
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": error_type, "code": code}},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    global _pipeline

    # Configure structured JSON logging (Track B)
    settings = get_settings()
    log_format = '{"time":"%(asctime)s","name":"%(name)s","level":"%(levelname)s","message":"%(message)s"}'
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=log_format,
    )

    logger.info("AION v%s starting on port %d", __version__, settings.port)
    logger.info("Fail mode: %s", settings.fail_mode.value)
    logger.info(
        "Modules: ESTIXE=%s NOMOS=%s METIS=%s",
        settings.estixe_enabled,
        settings.nomos_enabled,
        settings.metis_enabled,
    )

    # Build pipeline
    _pipeline = build_pipeline()

    yield

    # Graceful shutdown: flush telemetry, close clients
    await shutdown_telemetry()
    await shutdown_client()
    logger.info("AION shutdown complete")


app = FastAPI(
    title="AION",
    description="Motor Realtime do Sentinela — AI Control Plane",
    version=__version__,
    lifespan=lifespan,
)

# Register security middleware (Track A1)
app.add_middleware(AionSecurityMiddleware)


# ──────────────────────────────────────────────
# OpenAI-compatible endpoints
# ──────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint."""
    settings = get_settings()

    # Parse request body
    body = await request.json()

    # Validate message count (Track A1)
    messages = body.get("messages", [])
    if len(messages) > 100:
        return _error_response(400, "Too many messages (max 100)", "too_many_messages", "invalid_request")

    chat_request = ChatCompletionRequest(**body)

    # Resolve tenant
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    # Build pipeline context
    context = PipelineContext(tenant=tenant)

    # Ensure pipeline is initialized
    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline()

    # --- Run pre-LLM pipeline ---
    try:
        context = await _pipeline.run_pre(chat_request, context)
    except Exception:
        logger.exception("Pipeline pre-LLM failed (request_id=%s)", context.request_id)
        if settings.fail_mode == FailMode.CLOSED:
            return _error_response(503, "AION pipeline error (fail-closed)", "pipeline_error")
        context.decision = Decision.CONTINUE

    # --- Handle BLOCK ---
    if context.decision == Decision.BLOCK:
        reason = context.metadata.get("block_reason", "Request blocked by policy")
        await _pipeline.emit_telemetry(context)
        return _error_response(403, reason, "blocked_by_policy", "policy_error")

    # --- Handle BYPASS ---
    if context.decision == Decision.BYPASS and context.bypass_response:
        await _pipeline.emit_telemetry(context)

        resp_headers = {
            "X-Aion-Decision": "bypass",
            "X-Request-ID": context.request_id,
            **_pipeline.get_degraded_headers(),
        }

        if chat_request.stream:
            resp_headers["Cache-Control"] = "no-cache"
            resp_headers["Connection"] = "keep-alive"
            return StreamingResponse(
                build_bypass_stream(context.bypass_response),
                media_type="text/event-stream",
                headers=resp_headers,
            )

        return JSONResponse(content=context.bypass_response.model_dump(), headers=resp_headers)

    # --- Forward to LLM ---
    effective_request = context.modified_request or chat_request

    try:
        if chat_request.stream:
            async def stream_with_timeout():
                try:
                    async with asyncio.timeout(_STREAM_TIMEOUT):
                        async for chunk in forward_request_stream(
                            effective_request, context, settings
                        ):
                            yield chunk
                except asyncio.TimeoutError:
                    logger.warning("Stream timeout after %ds (request_id=%s)", _STREAM_TIMEOUT, context.request_id)
                finally:
                    await _pipeline.emit_telemetry(context)

            return StreamingResponse(
                stream_with_timeout(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Aion-Decision": "passthrough",
                    "X-Request-ID": context.request_id,
                    **_pipeline.get_degraded_headers(),
                },
            )
        else:
            t0 = time.perf_counter()
            response = await forward_request(effective_request, context, settings)
            llm_latency = (time.perf_counter() - t0) * 1000
            context.module_latencies["llm"] = round(llm_latency, 2)

            try:
                response = await _pipeline.run_post(response, context)
            except Exception:
                logger.exception("Pipeline post-LLM failed (request_id=%s)", context.request_id)

            await _pipeline.emit_telemetry(context)

            return JSONResponse(
                content=response.model_dump(),
                headers={
                    "X-Aion-Decision": "passthrough",
                    "X-Request-ID": context.request_id,
                    **_pipeline.get_degraded_headers(),
                },
            )

    except httpx.HTTPStatusError as e:
        await _pipeline.emit_telemetry(context)
        return _error_response(e.response.status_code, str(e), "llm_error", "upstream_error")
    except Exception:
        logger.exception("LLM forward failed (request_id=%s)", context.request_id)
        await _pipeline.emit_telemetry(context)
        return _error_response(502, "Failed to reach LLM provider", "llm_unreachable", "upstream_error")


# ──────────────────────────────────────────────
# Health & Observability
# ──────────────────────────────────────────────


@app.get("/health")
async def health():
    if not _pipeline:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "reason": "pipeline_not_initialized"})

    health_data = _pipeline.get_health()
    health_data["version"] = __version__
    health_data["active_modules"] = _pipeline.active_modules
    health_data["requests_in_flight"] = get_in_flight()

    mode = health_data.get("mode", "unknown")
    status = 200 if mode == "normal" else 207 if mode in ("degraded", "safe") else 503
    return JSONResponse(status_code=status, content=health_data)


@app.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics (Track B)."""
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

    return Response(content="\n".join(lines) + "\n", media_type="text/plain")


# ──────────────────────────────────────────────
# Control Plane (Track D)
# ──────────────────────────────────────────────


@app.put("/v1/killswitch")
async def activate_killswitch(request: Request):
    """Activate SAFE_MODE — all modules bypassed, pure passthrough."""
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = body.get("reason", "manual")
    _pipeline.activate_safe_mode(reason)
    return {"status": "safe_mode_active", "reason": reason}


@app.delete("/v1/killswitch")
async def deactivate_killswitch():
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    _pipeline.deactivate_safe_mode()
    return {"status": "normal_mode_restored"}


@app.put("/v1/modules/{module_name}/toggle")
async def toggle_module(module_name: str, request: Request):
    """Toggle a module on/off at runtime (Track D)."""
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    status = _pipeline._module_status.get(module_name)
    if not status:
        raise HTTPException(status_code=404, detail=f"Module '{module_name}' not found")

    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = body.get("enabled", not status.healthy)  # toggle if not specified
    status.healthy = enabled
    if not enabled:
        status.consecutive_failures = status.failure_threshold  # force degraded
    else:
        status.consecutive_failures = 0

    return {"module": module_name, "enabled": enabled}


# ──────────────────────────────────────────────
# Stats & Events
# ──────────────────────────────────────────────


@app.get("/v1/stats")
async def stats(request: Request):
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    return get_stats(tenant)


@app.get("/v1/events")
async def events(request: Request, limit: int = 100):
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    return get_recent_events(limit, tenant)


@app.get("/v1/models")
async def list_models():
    settings = get_settings()
    return {"models": [{"id": settings.default_model, "provider": settings.default_provider, "type": "default"}]}


@app.get("/v1/audit")
async def audit_log(limit: int = 100):
    """Get audit trail (Track E)."""
    return get_audit_log(limit)


# ──────────────────────────────────────────────
# Module management
# ──────────────────────────────────────────────


@app.post("/v1/estixe/intents/reload")
async def reload_intents():
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            await module._classifier.reload()
            return {"status": "reloaded", "intents": module._classifier.intent_count, "examples": module._classifier.example_count}
    raise HTTPException(status_code=404, detail="ESTIXE not active")


@app.post("/v1/estixe/policies/reload")
async def reload_policies():
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            await module._policy.reload()
            return {"status": "reloaded", "rules": module._policy.rule_count}
    raise HTTPException(status_code=404, detail="ESTIXE not active")


@app.get("/v1/behavior")
async def get_behavior(request: Request):
    from aion.metis.behavior import BehaviorDial
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    dial = BehaviorDial()
    config = await dial.get(tenant)
    if config is None:
        return {"tenant": tenant, "behavior": None}
    return {"tenant": tenant, "behavior": config.model_dump()}


@app.put("/v1/behavior")
async def set_behavior(request: Request):
    from aion.metis.behavior import BehaviorConfig, BehaviorDial
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    body = await request.json()
    config = BehaviorConfig(**body)
    dial = BehaviorDial()
    await dial.set(config, tenant)
    return {"tenant": tenant, "behavior": config.model_dump(), "status": "active"}


@app.delete("/v1/behavior")
async def delete_behavior(request: Request):
    from aion.metis.behavior import BehaviorDial
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    dial = BehaviorDial()
    await dial.delete(tenant)
    return {"tenant": tenant, "status": "removed"}


# ──────────────────────────────────────────────
# Data Management (Track E — LGPD)
# ──────────────────────────────────────────────


@app.delete("/v1/data/{tenant}")
async def delete_tenant_data(tenant: str):
    """Delete all data for a tenant (LGPD compliance)."""
    from aion.metis.behavior import BehaviorDial

    # Clear behavior
    dial = BehaviorDial()
    await dial.delete(tenant)

    # Clear telemetry events for this tenant
    from aion.shared.telemetry import _event_buffer
    original_len = len(_event_buffer)
    # Filter in-place
    for _ in range(original_len):
        if _event_buffer:
            event = _event_buffer.popleft()
            if event.get("tenant") != tenant:
                _event_buffer.append(event)

    return {"tenant": tenant, "status": "deleted"}


# Import for Response type
from starlette.responses import Response  # noqa: E402
