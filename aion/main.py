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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from aion import __version__
from aion.config import FailMode, get_settings
from aion.middleware import (
    AionSecurityMiddleware,
    audit,
    get_audit_log,
    get_in_flight,
    get_overrides,
    set_override,
    clear_overrides,
)
# Note: audit, get_audit_log, get_overrides, set_override, clear_overrides are all async now
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

# Background task handles
_snapshot_task: asyncio.Task | None = None
_approval_task: asyncio.Task | None = None


async def _record_all_outcomes(context: PipelineContext, response, settings) -> None:
    """Async fire-and-forget: record outcome to NEMOS for all modules.

    Runs via asyncio.create_task — adds 0ms to response path.
    """
    try:
        from aion.nemos import get_nemos
        from aion.nemos.models import OutcomeRecord

        nemos = get_nemos()
        now = time.time()

        # Extract actual tokens from response
        prompt_tokens = 0
        completion_tokens = 0
        if hasattr(response, "usage") and response.usage:
            prompt_tokens = response.usage.prompt_tokens or 0
            completion_tokens = response.usage.completion_tokens or 0

        # Calculate actual cost
        actual_cost = 0.0
        default_cost = 0.0
        model_name = context.selected_model or settings.default_model
        try:
            from aion.nomos.cost import estimate_request_cost
            from aion.nomos.registry import ModelRegistry
            from aion.config import get_nomos_settings
            registry = ModelRegistry(get_nomos_settings())
            await registry.load()
            model_config = registry.get_by_name(model_name)
            if model_config:
                actual_cost = estimate_request_cost(model_config, prompt_tokens, completion_tokens)
            default_config = registry.get_by_name(settings.default_model)
            if default_config:
                default_cost = estimate_request_cost(default_config, prompt_tokens, completion_tokens)
        except Exception:
            pass

        complexity = context.metadata.get("complexity_score", 0.0)
        intent = context.metadata.get("detected_intent", "unknown")
        tier = "simple" if complexity < 30 else "medium" if complexity < 60 else "complex"
        llm_latency = context.module_latencies.get("llm", 0.0)
        decision = context.decision.value if context.decision != Decision.CONTINUE else "continue"

        # 1. NOMOS: Decision Memory
        record = OutcomeRecord(
            request_id=context.request_id,
            tenant=context.tenant,
            timestamp=now,
            model=model_name,
            provider=context.selected_provider or settings.default_provider,
            complexity_score=complexity,
            detected_intent=intent,
            estimated_cost=context.metadata.get("estimated_cost", 0.0),
            actual_cost=actual_cost,
            actual_latency_ms=llm_latency,
            actual_prompt_tokens=prompt_tokens,
            actual_completion_tokens=completion_tokens,
            success=True,
            route_reason=context.metadata.get("route_reason", ""),
            decision=decision,
        )
        await nemos.record_outcome(record)

        # 2. Economics
        await nemos.record_economics(
            tenant=context.tenant,
            model=model_name,
            intent=intent,
            decision=decision,
            actual_cost=actual_cost,
            default_cost=default_cost,
            tokens=prompt_tokens + completion_tokens,
            latency_ms=llm_latency,
        )

        # 3. Baseline
        await nemos.update_baseline(
            tenant=context.tenant,
            latency_ms=llm_latency,
            cost=actual_cost,
            tokens=prompt_tokens + completion_tokens,
            model=model_name,
            intent=intent,
            complexity_tier=tier,
            decision=decision,
        )

    except Exception:
        logger.debug("NEMOS outcome recording failed (non-critical)", exc_info=True)


async def _snapshot_baselines_loop():
    """Background task: snapshot baselines hourly for trend computation."""
    while True:
        await asyncio.sleep(3600)
        try:
            from aion.nemos import get_nemos
            await get_nemos().snapshot_baselines_if_needed()
        except Exception:
            logger.debug("NEMOS snapshot failed (non-critical)", exc_info=True)


async def _approval_sweep_loop():
    """Background task: resolve expired approvals every 60s via their on_timeout policy."""
    while True:
        await asyncio.sleep(60)
        try:
            await _sweep_expired_approvals()
        except Exception:
            logger.debug("Approval sweep failed (non-critical)", exc_info=True)


async def _sweep_expired_approvals() -> int:
    """Check all pending approvals; resolve expired ones per on_timeout. Returns count resolved."""
    import time as _time
    from aion.nemos import get_nemos
    nemos = get_nemos()
    keys = await nemos._store.keys_by_prefix("aion:approval:")
    now = _time.time()
    resolved = 0
    for key in keys:
        record = await nemos._store.get_json(key)
        if not record or record.get("status") != "pending":
            continue
        if record.get("expires_at", 0) > now:
            continue
        # Expired — apply on_timeout
        on_timeout = record.get("on_timeout", "block")
        if on_timeout == "block":
            record["status"] = "expired"
        else:
            record["status"] = "timeout_fallback"
        record["resolved_by"] = "system:timeout"
        record["resolved_at"] = now
        await nemos._store.set_json(key, record, ttl_seconds=7 * 86400)
        resolved += 1
        logger.info("Approval %s resolved via timeout (on_timeout=%s)",
                    record.get("approval_request_id"), on_timeout)
    return resolved

# Override state (Track D)
_overrides: dict = {}


def _build_response_headers(context: PipelineContext) -> dict[str, str]:
    """Build standard response headers for every response."""
    headers = {
        "X-Aion-Decision": context.decision.value if context.decision != Decision.CONTINUE else "passthrough",
        "X-Request-ID": context.request_id,
    }
    # Cache status header
    if "cache_hit" in context.metadata:
        headers["X-Aion-Cache"] = "HIT" if context.metadata["cache_hit"] else "MISS"
    # Route reason from NOMOS
    route_reason = context.metadata.get("route_reason", "")
    if route_reason:
        headers["X-Aion-Route-Reason"] = route_reason
    # Degradation headers
    if _pipeline:
        headers.update(_pipeline.get_degraded_headers())
    return headers


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

    # Cold start: pre-load embedding model on startup (not on first request)
    if settings.estixe_enabled and not settings.safe_mode:
        t0 = time.perf_counter()
        for module in _pipeline._pre_modules:
            if module.name == "estixe":
                try:
                    await module.initialize()
                    logger.info("Cold start: ESTIXE initialized in %.1fs", time.perf_counter() - t0)
                except Exception:
                    logger.exception("Cold start: ESTIXE initialization failed")
                break

    _pipeline_ready.set()
    logger.info("AION pipeline ready")

    # Start NEMOS background snapshot task
    global _snapshot_task, _approval_task
    _snapshot_task = asyncio.create_task(_snapshot_baselines_loop())
    _approval_task = asyncio.create_task(_approval_sweep_loop())

    yield

    # Cancel background tasks on shutdown
    if _snapshot_task:
        _snapshot_task.cancel()
    if _approval_task:
        _approval_task.cancel()

    # Graceful shutdown: flush telemetry, close clients
    await shutdown_telemetry()
    await shutdown_client()
    logger.info("AION shutdown complete")


_pipeline_ready = asyncio.Event()


# ── Security headers middleware ──

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app = FastAPI(
    title="AION",
    description="Motor Realtime do Sentinela — AI Control Plane. "
                "Proxy gateway OpenAI-compatible com controle de PII, routing inteligente, e otimização de prompt.",
    version=__version__,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "LLM Proxy", "description": "OpenAI-compatible chat completions"},
        {"name": "Control Plane", "description": "Runtime configuration: killswitch, overrides, behavior dial, module toggle"},
        {"name": "Observability", "description": "Health, stats, events, metrics, economics, explainability"},
        {"name": "Data Management", "description": "LGPD compliance: data deletion, audit trail"},
    ],
)

# Register middleware stack (order matters: last added = first executed)
app.add_middleware(AionSecurityMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# CORS
_settings_cors = get_settings()
if _settings_cors.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _settings_cors.cors_origins.split(",")],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Aion-Decision", "X-Request-ID", "X-Aion-Route-Reason", "X-Aion-Mode"],
    )


# ──────────────────────────────────────────────
# OpenAI-compatible endpoints
# ──────────────────────────────────────────────


async def _resolve_operating_mode(tenant: str) -> str:
    """Ask NEMOS for the operating_mode; fall back to stateless if unavailable."""
    try:
        from aion.nemos import get_nemos
        return await get_nemos().get_operating_mode(tenant)
    except Exception:
        return "stateless"


def _active_module_names() -> list[str]:
    """Module names that actually ran (for capability reporting)."""
    if _pipeline is None:
        return []
    return [m.name for m in _pipeline._pre_modules]


def _add_contract_headers(headers: dict, contract, mode: str, *, idempotent_hit: bool = False) -> None:
    """Attach contract-derived headers common to all integration modes."""
    headers["X-Aion-Mode"] = mode
    headers["X-Aion-Contract-Version"] = contract.contract_version
    headers["X-Aion-Side-Effects-Possible"] = (
        "true" if contract.side_effect_level.value != "none" else "false"
    )
    dc = contract.decision_confidence
    headers["X-Aion-Decision-Confidence"] = f"{dc.score:.2f}"
    headers["X-Aion-Decision-Level"] = dc.level.value
    if idempotent_hit:
        headers["X-Aion-Idempotent-Hit"] = "true"


async def _idempotency_lookup(tenant: str, request: Request):
    """Return (idempotency_key, cached) — cached is None on miss."""
    key = request.headers.get("X-Idempotency-Key") or request.headers.get("x-idempotency-key")
    if not key:
        return None, None
    from aion.contract import get_idempotency_cache
    cached = await get_idempotency_cache().get(tenant, key)
    return key, cached


async def _idempotency_store(
    tenant: str, key: str | None, contract, response_dict: dict | None, executed: bool,
) -> None:
    if not key:
        return
    from aion.contract import get_idempotency_cache
    await get_idempotency_cache().set(tenant, key, contract, response_dict, executed)


@app.post("/v1/chat/completions", tags=["LLM Proxy"])
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint (Transparent mode)."""
    from aion.adapter import get_adapter
    from aion.contract import Action, build_contract
    from aion.contract.errors import ErrorType

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

    # --- Idempotency check ---
    idemp_key, cached = await _idempotency_lookup(tenant, request)
    if cached and cached.response:
        # Replay — return cached response + headers indicating idempotent hit
        headers = {"X-Request-ID": cached.contract.request_id}
        _add_contract_headers(headers, cached.contract, mode="transparent", idempotent_hit=True)
        return JSONResponse(content=cached.response, headers=headers)

    # Build pipeline context
    context = PipelineContext(tenant=tenant)
    context.original_request = chat_request
    if not context.modified_request:
        context.modified_request = chat_request
    if idemp_key:
        context.metadata["idempotency_key"] = idemp_key

    # Ensure pipeline is initialized
    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline()

    # --- Run pre-LLM pipeline ---
    t_pipeline = time.perf_counter()
    try:
        context = await _pipeline.run_pre(chat_request, context)
    except Exception:
        logger.exception("Pipeline pre-LLM failed (request_id=%s)", context.request_id)
        if settings.fail_mode == FailMode.CLOSED:
            return _error_response(503, "AION pipeline error (fail-closed)", "pipeline_error")
        context.decision = Decision.CONTINUE
    decision_latency_ms = (time.perf_counter() - t_pipeline) * 1000

    # --- Build DecisionContract (single canonical source) ---
    operating_mode = await _resolve_operating_mode(tenant)
    contract = build_contract(
        context,
        active_modules=_active_module_names(),
        operating_mode=operating_mode,
        decision_latency_ms=decision_latency_ms,
        environment=getattr(settings, "environment", "prod"),
    )

    # --- Handle BLOCK (preserve legacy error format) ---
    if contract.action == Action.BLOCK:
        await _pipeline.emit_telemetry(context)
        reason = (
            contract.error.detail if contract.error and contract.error.detail
            else context.metadata.get("block_reason", "Request blocked by policy")
        )
        headers = _build_response_headers(context)
        _add_contract_headers(headers, contract, mode="transparent")
        return JSONResponse(
            status_code=403,
            content={"error": {"message": reason, "type": "policy_error", "code": "blocked_by_policy"}},
            headers=headers,
        )

    # --- BYPASS — execute via adapter ---
    if contract.action == Action.BYPASS:
        await _pipeline.emit_telemetry(context)

        adapter = get_adapter()
        t_exec = time.perf_counter()
        result = await adapter.execute(contract, stream=chat_request.stream)
        execution_latency_ms = (time.perf_counter() - t_exec) * 1000

        headers = _build_response_headers(context)
        headers["X-Aion-Decision"] = "bypass"
        _add_contract_headers(headers, contract, mode="transparent")

        if not result.success:
            return _error_response(result.status_code, "Bypass execution failed", "bypass_error")

        if chat_request.stream and result.stream_iterator is not None:
            headers["Cache-Control"] = "no-cache"
            headers["Connection"] = "keep-alive"
            return StreamingResponse(
                result.stream_iterator,
                media_type="text/event-stream",
                headers=headers,
            )

        response_dict = result.response.model_dump()
        await _idempotency_store(tenant, idemp_key, contract, response_dict, executed=True)
        return JSONResponse(content=response_dict, headers=headers)

    # --- CALL_LLM path (streaming preserves existing behavior) ---
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

            stream_headers = _build_response_headers(context)
            stream_headers["X-Aion-Decision"] = "passthrough"
            stream_headers["Cache-Control"] = "no-cache"
            stream_headers["Connection"] = "keep-alive"
            _add_contract_headers(stream_headers, contract, mode="transparent")
            return StreamingResponse(
                stream_with_timeout(),
                media_type="text/event-stream",
                headers=stream_headers,
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

            # Record outcome to NEMOS (async, 0ms on response path)
            asyncio.create_task(_record_all_outcomes(context, response, settings))

            # Store in semantic cache (async, fire-and-forget)
            try:
                from aion.cache import get_cache
                _cache = get_cache()
                if _cache.enabled:
                    asyncio.create_task(asyncio.to_thread(
                        _cache.store, effective_request, response, context
                    ))
            except Exception:
                pass  # cache store is non-critical

            pass_headers = _build_response_headers(context)
            pass_headers["X-Aion-Decision"] = "passthrough"
            _add_contract_headers(pass_headers, contract, mode="transparent")
            response_dict = response.model_dump()
            await _idempotency_store(tenant, idemp_key, contract, response_dict, executed=True)
            return JSONResponse(content=response_dict, headers=pass_headers)

    except httpx.HTTPStatusError as e:
        await _pipeline.emit_telemetry(context)
        return _error_response(e.response.status_code, str(e), "llm_error", "upstream_error")
    except Exception:
        logger.exception("LLM forward failed (request_id=%s)", context.request_id)
        await _pipeline.emit_telemetry(context)
        return _error_response(502, "Failed to reach LLM provider", "llm_unreachable", "upstream_error")


# ──────────────────────────────────────────────
# Integration Modes — Assisted + Decision
# ──────────────────────────────────────────────


async def _run_pipeline_and_build_contract(
    chat_request: ChatCompletionRequest,
    tenant: str,
    *,
    settings,
) -> tuple[PipelineContext, "DecisionContract", float]:  # noqa: F821
    """Shared helper: run pre-LLM pipeline and build the contract.

    Used by Assisted (/v1/chat/assisted) and Decision (/v1/decisions) modes.
    Transparent (/v1/chat/completions) uses its own flow for backward compat.
    """
    from aion.contract import build_contract

    context = PipelineContext(tenant=tenant)
    context.original_request = chat_request
    if not context.modified_request:
        context.modified_request = chat_request

    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline()

    t_pipeline = time.perf_counter()
    try:
        context = await _pipeline.run_pre(chat_request, context)
    except Exception:
        logger.exception("Pipeline pre-LLM failed (request_id=%s)", context.request_id)
        if settings.fail_mode == FailMode.CLOSED:
            raise
        context.decision = Decision.CONTINUE
    decision_latency_ms = (time.perf_counter() - t_pipeline) * 1000

    operating_mode = await _resolve_operating_mode(tenant)
    contract = build_contract(
        context,
        active_modules=_active_module_names(),
        operating_mode=operating_mode,
        decision_latency_ms=decision_latency_ms,
        environment=getattr(settings, "environment", "prod"),
    )
    return context, contract, decision_latency_ms


@app.post("/v1/chat/assisted", tags=["LLM Proxy"])
async def chat_assisted(request: Request):
    """Assisted mode — AION executa, retorna response + DecisionContract.

    Response: {"response": ChatCompletionResponse, "contract": DecisionContract}
    """
    from aion.adapter import get_adapter
    from aion.contract import Action

    settings = get_settings()
    body = await request.json()

    if len(body.get("messages", [])) > 100:
        return _error_response(400, "Too many messages (max 100)", "too_many_messages", "invalid_request")

    try:
        chat_request = ChatCompletionRequest(**body)
    except Exception as exc:
        return _error_response(400, f"Invalid request: {exc}", "invalid_request")

    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    # Idempotency
    idemp_key, cached = await _idempotency_lookup(tenant, request)
    if cached:
        headers = {"X-Request-ID": cached.contract.request_id}
        _add_contract_headers(headers, cached.contract, mode="assisted", idempotent_hit=True)
        return JSONResponse(
            content={"response": cached.response, "contract": cached.contract.model_dump()},
            headers=headers,
        )

    try:
        context, contract, decision_latency_ms = await _run_pipeline_and_build_contract(
            chat_request, tenant, settings=settings,
        )
    except Exception:
        return _error_response(503, "AION pipeline error (fail-closed)", "pipeline_error")

    if idemp_key:
        context.metadata["idempotency_key"] = idemp_key
        contract.idempotency_key = idemp_key

    await _pipeline.emit_telemetry(context)

    # Handle BLOCK — return contract with error inside, HTTP 403
    if contract.action == Action.BLOCK:
        headers = _build_response_headers(context)
        _add_contract_headers(headers, contract, mode="assisted")
        return JSONResponse(
            status_code=403,
            content={"response": None, "contract": contract.model_dump()},
            headers=headers,
        )

    # Execute via adapter (streaming not supported in Assisted v1)
    adapter = get_adapter()
    t_exec = time.perf_counter()
    result = await adapter.execute(contract, stream=False)
    execution_latency_ms = (time.perf_counter() - t_exec) * 1000

    # Update metrics in the contract so client sees full picture
    contract.meta.metrics.execution_latency_ms = round(execution_latency_ms, 2)
    contract.meta.metrics.total_latency_ms = round(decision_latency_ms + execution_latency_ms, 2)
    if result.response and result.response.usage:
        contract.meta.metrics.tokens_used = result.response.usage.total_tokens or 0

    headers = _build_response_headers(context)
    _add_contract_headers(headers, contract, mode="assisted")

    if not result.success:
        return JSONResponse(
            status_code=result.status_code,
            content={
                "response": None,
                "contract": contract.model_dump(),
                "error": result.error.model_dump() if result.error else None,
            },
            headers=headers,
        )

    # Record outcome to NEMOS (same as Transparent)
    if contract.action == Action.CALL_LLM:
        asyncio.create_task(_record_all_outcomes(context, result.response, settings))

    response_dict = result.response.model_dump() if result.response else None
    body_out = {
        "response": response_dict,
        "contract": contract.model_dump(),
    }
    if result.raw_service_response is not None:
        body_out["raw_service_response"] = result.raw_service_response

    await _idempotency_store(tenant, idemp_key, contract, response_dict, executed=True)
    return JSONResponse(content=body_out, headers=headers)


@app.post("/v1/decisions", tags=["LLM Proxy"])
async def decisions(request: Request):
    """Decision mode — AION decide, nao executa. Retorna DecisionContract cru.

    O ExecutionAdapter NUNCA e invocado neste endpoint. Cliente executa por conta.
    """
    settings = get_settings()
    body = await request.json()

    if len(body.get("messages", [])) > 100:
        return _error_response(400, "Too many messages (max 100)", "too_many_messages", "invalid_request")

    try:
        chat_request = ChatCompletionRequest(**body)
    except Exception as exc:
        return _error_response(400, f"Invalid request: {exc}", "invalid_request")

    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    # Idempotency
    idemp_key, cached = await _idempotency_lookup(tenant, request)
    if cached:
        headers = {"X-Request-ID": cached.contract.request_id}
        _add_contract_headers(headers, cached.contract, mode="decision", idempotent_hit=True)
        return JSONResponse(content=cached.contract.model_dump(), headers=headers)

    try:
        context, contract, _ = await _run_pipeline_and_build_contract(
            chat_request, tenant, settings=settings,
        )
    except Exception:
        return _error_response(503, "AION pipeline error (fail-closed)", "pipeline_error")

    if idemp_key:
        contract.idempotency_key = idemp_key

    await _pipeline.emit_telemetry(context)

    headers = _build_response_headers(context)
    _add_contract_headers(headers, contract, mode="decision")

    # Decision mode: execution_latency is always 0 (adapter not invoked)
    contract.meta.metrics.execution_latency_ms = 0.0
    contract.meta.metrics.total_latency_ms = contract.meta.metrics.decision_latency_ms

    # Cache contract only (no response since no execution)
    await _idempotency_store(tenant, idemp_key, contract, response_dict=None, executed=False)
    return JSONResponse(content=contract.model_dump(), headers=headers)


# ──────────────────────────────────────────────
# Human Approval lifecycle
# ──────────────────────────────────────────────


@app.get("/v1/approvals/{approval_id}", tags=["Control Plane"])
async def get_approval(approval_id: str):
    """Polling endpoint — returns the current status of a human-approval request."""
    from aion.adapter.approval_executor import _approval_key
    from aion.nemos import get_nemos
    record = await get_nemos()._store.get_json(_approval_key(approval_id))
    if not record:
        return _error_response(404, f"Approval '{approval_id}' not found", "not_found", "invalid_request")
    return record


@app.post("/v1/approvals/{approval_id}/resolve", tags=["Control Plane"])
async def resolve_approval(approval_id: str, request: Request):
    """Resolve a pending approval (approved or denied).

    Body: ``{"status": "approved|denied", "approver": "string"}``
    """
    import time as _time
    from aion.adapter.approval_executor import _approval_key
    from aion.nemos import get_nemos

    body = await request.json()
    new_status = body.get("status")
    if new_status not in ("approved", "denied"):
        return _error_response(400, "status must be 'approved' or 'denied'", "invalid_status", "invalid_request")
    approver = body.get("approver", "unknown")

    nemos = get_nemos()
    key = _approval_key(approval_id)
    record = await nemos._store.get_json(key)
    if not record:
        return _error_response(404, f"Approval '{approval_id}' not found", "not_found", "invalid_request")
    if record.get("status") != "pending":
        return _error_response(
            409, f"Approval already resolved (status={record['status']})",
            "already_resolved", "invalid_request",
        )

    record["status"] = new_status
    record["resolved_by"] = approver
    record["resolved_at"] = _time.time()
    await nemos._store.set_json(key, record, ttl_seconds=7 * 86400)
    return {"approval_request_id": approval_id, "status": new_status, "resolved_by": approver}


@app.get("/v1/approvals", tags=["Control Plane"])
async def list_approvals(
    tenant: str | None = None, status: str | None = "pending", limit: int = 50,
):
    """List approvals filtered by tenant and status."""
    from aion.nemos import get_nemos
    nemos = get_nemos()
    keys = await nemos._store.keys_by_prefix("aion:approval:")
    items = []
    for key in keys:
        rec = await nemos._store.get_json(key)
        if not rec:
            continue
        if tenant and rec.get("tenant") != tenant:
            continue
        if status and rec.get("status") != status:
            continue
        items.append(rec)
        if len(items) >= limit:
            break
    return {"approvals": items, "count": len(items)}


# ──────────────────────────────────────────────
# Health & Observability
# ──────────────────────────────────────────────


@app.get("/health", tags=["Observability"])
async def health():
    if not _pipeline:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "reason": "pipeline_not_initialized", "ready": False})

    health_data = _pipeline.get_health()
    health_data["version"] = __version__
    health_data["active_modules"] = _pipeline.active_modules
    health_data["requests_in_flight"] = get_in_flight()
    health_data["ready"] = _pipeline_ready.is_set()

    mode = health_data.get("mode", "unknown")
    status = 200 if mode == "normal" else 207 if mode in ("degraded", "safe") else 503
    return JSONResponse(status_code=status, content=health_data)


@app.get("/ready", tags=["Observability"])
async def readiness():
    """Kubernetes readiness probe. Returns 200 only when pipeline is fully initialized."""
    if _pipeline_ready.is_set():
        return {"ready": True}
    return JSONResponse(status_code=503, content={"ready": False})


@app.get("/metrics", tags=["Observability"])
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


@app.put("/v1/killswitch", tags=["Control Plane"])
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


@app.delete("/v1/killswitch", tags=["Control Plane"])
async def deactivate_killswitch():
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    _pipeline.deactivate_safe_mode()
    return {"status": "normal_mode_restored"}


@app.get("/v1/overrides", tags=["Control Plane"])
async def get_overrides_endpoint(request: Request):
    """Get current runtime overrides for tenant."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    return await get_overrides(tenant)


@app.put("/v1/overrides", tags=["Control Plane"])
async def set_overrides_endpoint(request: Request):
    """Set runtime overrides. Priority: request header > tenant > global override."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    try:
        body = await request.json()
    except Exception:
        body = {}
    for k, v in body.items():
        await set_override(k, v, tenant)
    return {"status": "active", "overrides": await get_overrides(tenant)}


@app.delete("/v1/overrides", tags=["Control Plane"])
async def clear_overrides_endpoint(request: Request):
    """Clear all runtime overrides for tenant."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    await clear_overrides(tenant)
    return {"status": "cleared"}


@app.put("/v1/modules/{module_name}/toggle", tags=["Control Plane"])
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


@app.get("/v1/stats", tags=["Observability"])
async def stats(request: Request):
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    return get_stats(tenant)


@app.get("/v1/events", tags=["Observability"])
async def events(request: Request, limit: int = 100):
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    return get_recent_events(limit, tenant)


@app.get("/v1/models", tags=["Observability"])
async def list_models():
    settings = get_settings()
    return {"models": [{"id": settings.default_model, "provider": settings.default_provider, "type": "default"}]}


@app.get("/v1/audit", tags=["Data Management"])
async def audit_log_endpoint(request: Request, limit: int = 100):
    """Get audit trail for tenant."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    return await get_audit_log(limit, tenant)


# ──────────────────────────────────────────────
# Module management
# ──────────────────────────────────────────────


@app.post("/v1/estixe/intents/reload", tags=["Control Plane"])
async def reload_intents():
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            await module._classifier.reload()
            return {"status": "reloaded", "intents": module._classifier.intent_count, "examples": module._classifier.example_count}
    raise HTTPException(status_code=404, detail="ESTIXE not active")


@app.post("/v1/estixe/policies/reload", tags=["Control Plane"])
async def reload_policies():
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            await module._policy.reload()
            return {"status": "reloaded", "rules": module._policy.rule_count}
    raise HTTPException(status_code=404, detail="ESTIXE not active")


@app.get("/v1/behavior", tags=["Control Plane"])
async def get_behavior(request: Request):
    from aion.metis.behavior import BehaviorDial
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    dial = BehaviorDial()
    config = await dial.get(tenant)
    if config is None:
        return {"tenant": tenant, "behavior": None}
    return {"tenant": tenant, "behavior": config.model_dump()}


@app.put("/v1/behavior", tags=["Control Plane"])
async def set_behavior(request: Request):
    from aion.metis.behavior import BehaviorConfig, BehaviorDial
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    body = await request.json()
    config = BehaviorConfig(**body)
    dial = BehaviorDial()
    await dial.set(config, tenant)
    return {"tenant": tenant, "behavior": config.model_dump(), "status": "active"}


@app.delete("/v1/behavior", tags=["Control Plane"])
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


@app.delete("/v1/data/{tenant}", tags=["Data Management"])
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

    # Clear semantic cache
    try:
        from aion.cache import get_cache
        get_cache().delete_tenant(tenant)
    except Exception:
        logger.debug("Cache delete failed for tenant %s", tenant)

    # Clear NEMOS data (decision memory, economics, baseline)
    nemos_deleted = 0
    try:
        from aion.nemos import get_nemos
        nemos_deleted = await get_nemos().delete_tenant_data(tenant)
    except Exception:
        logger.debug("NEMOS delete failed for tenant %s", tenant)

    return {"tenant": tenant, "status": "deleted", "nemos_keys_deleted": nemos_deleted}


# ──────────────────────────────────────────────
# Runtime Economics & Explainability
# ──────────────────────────────────────────────


@app.get("/v1/economics", tags=["Observability"])
async def runtime_economics(request: Request):
    """Runtime economics — visible cost savings and efficiency metrics.

    Shows exactly how much the AION saved in tokens, cost, and LLM calls.
    """
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


@app.get("/v1/cache/stats", tags=["Observability"])
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


@app.get("/v1/explain/{request_id}", tags=["Observability"])
async def explain_decision(request_id: str, request: Request):
    """Explainability — full trace of what AION decided for a specific request.

    Returns the complete DecisionRecord: which modules ran, what they decided,
    why, what policies matched, what cost was estimated, what was saved.
    """
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    # Find the event in telemetry
    events = get_recent_events(limit=1000, tenant=tenant)
    for event in events:
        if event.get("request_id") == request_id:
            return {
                "request_id": request_id,
                "tenant": tenant,
                "found": True,
                "decision": event.get("decision"),
                "model_used": event.get("model_used"),
                "module": event.get("module"),
                "tokens_saved": event.get("tokens_saved", 0),
                "cost_saved": event.get("cost_saved", 0.0),
                "latency_ms": event.get("latency_ms", 0.0),
                "metadata": event.get("metadata", {}),
                "timestamp": event.get("timestamp"),
            }

    return {"request_id": request_id, "found": False, "message": "Request not found in recent events"}


@app.get("/v1/metrics/tenant/{tenant_id}", tags=["Observability"])
async def tenant_metrics(tenant_id: str):
    """Per-tenant metrics — decisions, savings, latency for a specific tenant."""
    stats_data = get_stats(tenant_id)
    return {
        "tenant": tenant_id,
        "metrics": stats_data,
    }


# ──────────────────────────────────────────────
# NEMOS — Intelligence & Benchmark endpoints
# ──────────────────────────────────────────────


@app.get("/v1/benchmark/{tenant_id}", tags=["Observability"])
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


@app.get("/v1/recommendations/{tenant_id}", tags=["Observability"])
async def tenant_recommendations(tenant_id: str):
    """AI-generated recommendations for optimizing a tenant's AI operations."""
    from aion.nemos import get_nemos
    recs = await get_nemos().get_recommendations(tenant_id)
    return {
        "tenant": tenant_id,
        "recommendations": [r.to_dict() for r in recs],
        "count": len(recs),
    }


# Import for Response type
from starlette.responses import Response  # noqa: E402
