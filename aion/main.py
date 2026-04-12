"""AION — Motor Realtime do Sentinela.

FastAPI application serving as an OpenAI-compatible proxy gateway.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from aion import __version__
from aion.config import FailMode, get_settings
from aion.pipeline import Pipeline, build_pipeline
from aion.proxy import (
    build_bypass_stream,
    forward_request,
    forward_request_stream,
    shutdown_client,
)
from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatMessage,
    Decision,
    PipelineContext,
)
from aion.shared.telemetry import get_recent_events, get_stats

logger = logging.getLogger("aion")

# --- Global state ---
_pipeline: Pipeline | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    global _pipeline

    # Configure logging
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
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

    # Shutdown
    await shutdown_client()
    logger.info("AION shutdown complete")


app = FastAPI(
    title="AION",
    description="Motor Realtime do Sentinela — controla a IA em tempo real",
    version=__version__,
    lifespan=lifespan,
)


# ──────────────────────────────────────────────
# OpenAI-compatible endpoints
# ──────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint."""
    settings = get_settings()

    # Parse request body
    body = await request.json()
    chat_request = ChatCompletionRequest(**body)

    # Resolve tenant
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    # Build pipeline context
    context = PipelineContext(tenant=tenant)

    # Ensure pipeline is initialized (handles test environment where lifespan may not run)
    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline()

    # --- Run pre-LLM pipeline ---
    try:
        context = await _pipeline.run_pre(chat_request, context)
    except Exception:
        logger.exception("Pipeline pre-LLM failed")
        if settings.fail_mode == FailMode.CLOSED:
            raise HTTPException(status_code=503, detail="AION pipeline error (fail-closed)")
        # fail-open: proceed as if no modules exist
        context.decision = Decision.CONTINUE

    # --- Handle BLOCK ---
    if context.decision == Decision.BLOCK:
        reason = context.metadata.get("block_reason", "Request blocked by policy")
        await _pipeline.emit_telemetry(context)
        raise HTTPException(status_code=403, detail=reason)

    # --- Handle BYPASS ---
    if context.decision == Decision.BYPASS and context.bypass_response:
        await _pipeline.emit_telemetry(context)

        if chat_request.stream:
            stream_headers = {
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Aion-Decision": "bypass",
                "X-Request-ID": context.request_id,
                **_pipeline.get_degraded_headers(),
            }
            return StreamingResponse(
                build_bypass_stream(context.bypass_response),
                media_type="text/event-stream",
                headers=stream_headers,
            )

        resp_headers = {"X-Aion-Decision": "bypass", "X-Request-ID": context.request_id}
        resp_headers.update(_pipeline.get_degraded_headers())
        return JSONResponse(
            content=context.bypass_response.model_dump(),
            headers=resp_headers,
        )

    # --- Forward to LLM ---
    effective_request = context.modified_request or chat_request

    try:
        if chat_request.stream:
            # Streaming mode
            async def stream_with_telemetry():
                async for chunk in forward_request_stream(
                    effective_request, context, settings
                ):
                    yield chunk
                await _pipeline.emit_telemetry(context)

            pass_stream_headers = {
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Aion-Decision": "passthrough",
                "X-Request-ID": context.request_id,
                **_pipeline.get_degraded_headers(),
            }
            return StreamingResponse(
                stream_with_telemetry(),
                media_type="text/event-stream",
                headers=pass_stream_headers,
            )
        else:
            # Batch mode
            t0 = time.perf_counter()
            response = await forward_request(effective_request, context, settings)
            llm_latency = (time.perf_counter() - t0) * 1000
            context.module_latencies["llm"] = round(llm_latency, 2)

            # Run post-LLM pipeline
            try:
                response = await _pipeline.run_post(response, context)
            except Exception:
                logger.exception("Pipeline post-LLM failed")
                # fail-open: return original response

            await _pipeline.emit_telemetry(context)

            pass_headers = {
                "X-Aion-Decision": "passthrough",
                "X-Request-ID": context.request_id,
                **_pipeline.get_degraded_headers(),
            }
            return JSONResponse(
                content=response.model_dump(),
                headers=pass_headers,
            )

    except httpx.HTTPStatusError as e:
        await _pipeline.emit_telemetry(context)
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except Exception:
        logger.exception("LLM forward failed")
        await _pipeline.emit_telemetry(context)
        raise HTTPException(status_code=502, detail="Failed to reach LLM provider")


# ──────────────────────────────────────────────
# AION management endpoints
# ──────────────────────────────────────────────


@app.get("/health")
async def health():
    if not _pipeline:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "reason": "pipeline_not_initialized"},
        )

    health_data = _pipeline.get_health()
    health_data["version"] = __version__
    health_data["active_modules"] = _pipeline.active_modules

    mode = health_data.get("mode", "unknown")
    if mode == "normal":
        return JSONResponse(status_code=200, content=health_data)
    elif mode == "degraded":
        return JSONResponse(status_code=207, content=health_data)
    elif mode == "safe":
        return JSONResponse(status_code=207, content=health_data)
    else:
        return JSONResponse(status_code=503, content=health_data)


@app.put("/v1/killswitch")
async def activate_killswitch(request: Request):
    """Activate SAFE_MODE — all modules bypassed, pure passthrough."""
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    reason = body.get("reason", "manual")
    _pipeline.activate_safe_mode(reason)
    return {"status": "safe_mode_active", "reason": reason}


@app.delete("/v1/killswitch")
async def deactivate_killswitch():
    """Deactivate SAFE_MODE — restore normal operation."""
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    _pipeline.deactivate_safe_mode()
    return {"status": "normal_mode_restored"}


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
    """List available models (no credentials exposed)."""
    settings = get_settings()
    models = [
        {
            "id": settings.default_model,
            "provider": settings.default_provider,
            "type": "default",
        }
    ]
    return {"models": models}


@app.post("/v1/estixe/intents/reload")
async def reload_intents():
    """Hot-reload ESTIXE intents."""
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            await module._classifier.reload()
            return {
                "status": "reloaded",
                "intents": module._classifier.intent_count,
                "examples": module._classifier.example_count,
            }

    raise HTTPException(status_code=404, detail="ESTIXE not active")


@app.get("/v1/behavior")
async def get_behavior(request: Request):
    """Get current behavior dial settings."""
    from aion.metis.behavior import BehaviorDial
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    dial = BehaviorDial()
    config = await dial.get(tenant)
    if config is None:
        return {"tenant": tenant, "behavior": None, "message": "No behavior configured"}
    return {"tenant": tenant, "behavior": config.model_dump()}


@app.put("/v1/behavior")
async def set_behavior(request: Request):
    """Set behavior dial — takes effect immediately, no deploy needed."""
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
    """Remove behavior dial — revert to default LLM behavior."""
    from aion.metis.behavior import BehaviorDial
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    dial = BehaviorDial()
    await dial.delete(tenant)
    return {"tenant": tenant, "status": "removed"}


@app.post("/v1/estixe/policies/reload")
async def reload_policies():
    """Hot-reload ESTIXE policies."""
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            await module._policy.reload()
            return {"status": "reloaded", "rules": module._policy.rule_count}

    raise HTTPException(status_code=404, detail="ESTIXE not active")


# ──────────────────────────────────────────────
# Import guard for httpx
# ──────────────────────────────────────────────
import httpx  # noqa: E402
