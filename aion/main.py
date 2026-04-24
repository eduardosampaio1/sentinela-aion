"""AION — Motor Realtime do Sentinela.

FastAPI application serving as an OpenAI-compatible proxy gateway.
Modes: Normal | Degraded | Safe (SAFE_MODE)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
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
    import os
    replica_id = os.environ.get("AION_REPLICA_ID", "local")
    headers = {
        "X-Aion-Decision": context.decision.value if context.decision != Decision.CONTINUE else "passthrough",
        "X-Request-ID": context.request_id,
        "X-Aion-Replica": replica_id,
    }
    # Cache status header
    if "cache_hit" in context.metadata:
        headers["X-Aion-Cache"] = "HIT" if context.metadata["cache_hit"] else "MISS"
    # Route reason from NOMOS — sanitize para Latin-1 (HTTP headers nao aceitam Unicode)
    route_reason = context.metadata.get("route_reason", "")
    if route_reason:
        headers["X-Aion-Route-Reason"] = route_reason.replace("\u2192", "->").encode("latin-1", errors="replace").decode("latin-1")
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

    # License validation — must run before anything else.
    # INVALID = explicit error banner + sys.exit(1). No silent failure.
    from aion.license import validate_license_or_abort, LicenseState
    lic = validate_license_or_abort()

    # Gating: disable premium modules if license expired
    if lic.state == LicenseState.EXPIRED:
        logger.warning("Licença expirada — desabilitando NOMOS e METIS avançado (fail-open)")
        settings.nomos_enabled = False
        settings.metis_enabled = False

    # Load persisted overrides from disk (fallback quando sem Redis) — evita perder
    # config de tenant em restart do AION.
    from aion.middleware import _load_overrides_from_disk
    _load_overrides_from_disk()

    # OpenTelemetry tracing — no-op se OTEL_EXPORTER_OTLP_ENDPOINT não setado
    try:
        from aion.observability import setup_telemetry
        setup_telemetry(app)
    except Exception as e:
        logger.warning("OpenTelemetry setup failed (non-fatal): %s", e)

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
        expose_headers=["X-Aion-Decision", "X-Request-ID", "X-Aion-Route-Reason", "X-Aion-Mode", "X-Aion-Replica"],
    )


# ──────────────────────────────────────────────
# Global exception handlers
# ──────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def _handle_request_validation_error(request: Request, exc: RequestValidationError):
    return _error_response(422, f"Request validation error: {exc}", "validation_error", "invalid_request_error")


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


@app.post("/v1/decide", tags=["Decision Gateway"])
async def decide(request: Request):
    """Pure decision endpoint: retorna CONTINUE/BLOCK/BYPASS SEM chamar LLM.

    AION é um gate pré-LLM. Este endpoint expõe essa semântica pura para clientes
    que já têm seu próprio LLM/provider e só querem usar o AION como controle de
    segurança + cache de decisão.

    Target: milhões de decisões/s quando cache warm (>80% hit rate esperado).

    Request body: OpenAI ChatCompletion format (messages, model, etc).
    Response:
      {
        "decision": "continue" | "block" | "bypass",
        "reason": string | null,
        "bypass_response": {...} | null,        # quando decision=bypass
        "filtered_messages": [...] | null,      # quando PII foi redacted
        "detected_intent": string | null,
        "confidence": float | null,
        "metadata": {...},                       # sinais ESTIXE
        "latency_ms": float,
        "source": "cache" | "pipeline"          # indicador de fast-path
      }
    """
    settings = get_settings()
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    t0 = time.perf_counter()
    try:
        body = await request.json()
    except Exception:
        return _error_response(400, "Invalid JSON body", "invalid_json", "invalid_request")

    from aion.shared.schemas import ChatCompletionRequest, PipelineContext
    try:
        chat_request = ChatCompletionRequest(**body)
    except Exception as e:
        return _error_response(422, f"Invalid request format: {e}", "validation_error", "invalid_request_error")

    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    context = PipelineContext(
        tenant=tenant,
        original_request=chat_request,
        modified_request=chat_request.model_copy(deep=True),
    )

    # Propaga pii_policy + thresholds se o cliente mandou override
    if "pii_policy" in body:
        context.metadata["pii_policy"] = body["pii_policy"]
    if "estixe_thresholds" in body:
        context.metadata["estixe_thresholds"] = body["estixe_thresholds"]

    # Apply per-tenant shadow_mode override (same logic as /v1/chat/completions)
    _decide_ov = await get_overrides(tenant)
    if _decide_ov.get("shadow_mode"):
        context.metadata["shadow_mode"] = True

    # Roda SÓ os pre-modules (ESTIXE). Não chama LLM.
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            await module.process(chat_request, context)
            break

    latency = (time.perf_counter() - t0) * 1000
    result = context.estixe_result

    resp = {
        "decision": result.action.value.lower() if result else "continue",
        "reason": result.block_reason if result else None,
        "detected_intent": result.intent_detected if result else None,
        "confidence": result.intent_confidence if result else None,
        "pii_sanitized": result.pii_sanitized if result else False,
        "metadata": dict(context.metadata),
        "latency_ms": round(latency, 3),
        "source": context.metadata.get("decision_source", "pipeline"),
    }

    # Se bloqueou, devolve 200 com decision=block (não 403 — cliente decide o que fazer)
    # Isso é diferente de /v1/chat/completions que aplica a decisão.
    headers = {
        "X-Aion-Replica": os.environ.get("AION_REPLICA_ID", "local"),
        "X-Aion-Decision": resp["decision"],
        "X-Aion-Decision-Source": resp["source"],
    }
    return JSONResponse(content=resp, headers=headers)


@app.post("/v1/chat/completions", tags=["LLM Proxy"])
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint (Transparent mode)."""
    from aion.adapter import get_adapter
    from aion.contract import Action, build_contract
    from aion.contract.errors import ErrorType

    settings = get_settings()

    # Parse request body — guard against malformed JSON or bad encoding (e.g. cp1252 curl)
    try:
        body = await request.json()
    except Exception:
        return _error_response(
            400,
            "Invalid request body: malformed JSON or non-UTF-8 encoding",
            "invalid_request",
            "invalid_request_error",
        )

    # Validate message count (Track A1)
    messages = body.get("messages", [])
    if len(messages) > 100:
        return _error_response(400, "Too many messages (max 100)", "too_many_messages", "invalid_request")

    try:
        chat_request = ChatCompletionRequest(**body)
    except Exception as e:
        return _error_response(422, f"Invalid request format: {e}", "validation_error", "invalid_request_error")

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

    # Apply per-tenant runtime overrides to pipeline context (sim customization)
    _tenant_ov = await get_overrides(tenant)
    if "pii_policy" in _tenant_ov:
        context.metadata["pii_policy"] = _tenant_ov["pii_policy"]
    if "estixe_thresholds" in _tenant_ov:
        # Per-tenant risk threshold overrides, e.g. {"fraud_enablement": 0.70}
        # Passed to RiskClassifier.classify() without mutating shared settings.
        context.metadata["estixe_thresholds"] = _tenant_ov["estixe_thresholds"]
    if _tenant_ov.get("shadow_mode"):
        # Global observation mode: all risk matches observe without blocking.
        # Set via PUT /v1/overrides {"shadow_mode": true} for new-client calibration.
        context.metadata["shadow_mode"] = True

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
            # Output guard para streaming: buffer-accumulate-check-flush.
            # Trade-off v1: usuario recebe todos os tokens de uma vez no fim, em vez
            # de incrementalmente. Isso garante S2' (PII) e S3' (risco estrutural)
            # sobre o output completo. V2 ideal: check incremental em windows.
            async def stream_with_guard():
                buffered_chunks: list[str] = []
                accumulated_content: list[str] = []

                try:
                    async with asyncio.timeout(_STREAM_TIMEOUT):
                        async for chunk in forward_request_stream(
                            effective_request, context, settings
                        ):
                            buffered_chunks.append(chunk)
                            # Extrai delta.content de cada chunk SSE para o buffer de verificacao
                            if chunk.startswith("data:"):
                                payload = chunk[5:].strip()
                                if payload and payload != "[DONE]":
                                    try:
                                        import json as _json
                                        obj = _json.loads(payload)
                                        for ch in obj.get("choices", []) or []:
                                            delta = ch.get("delta") or {}
                                            content = delta.get("content")
                                            if content:
                                                accumulated_content.append(content)
                                    except Exception:
                                        pass  # Chunk nao-JSON (heartbeat etc) — preserva, nao analisa
                except asyncio.TimeoutError:
                    logger.warning("Stream timeout after %ds (request_id=%s)", _STREAM_TIMEOUT, context.request_id)

                # Verificacao do output COMPLETO apos buffer fechado
                full_text = "".join(accumulated_content)
                blocked_by_guard = False
                if settings.estixe_enabled and full_text:
                    from aion.shared.contracts import EstixeAction as _EA
                    for _mod in _pipeline._pre_modules:
                        if _mod.name == "estixe":
                            _out_check = await _mod.check_llm_output(full_text, context)
                            if _out_check.action == _EA.BLOCK:
                                blocked_by_guard = True
                                context.metadata["output_stream_blocked"] = True
                                context.metadata["output_stream_block_reason"] = _out_check.block_reason
                                logger.warning(
                                    "STREAM OUTPUT BLOQUEADO (buffered): %s",
                                    _out_check.block_reason,
                                )
                            elif _out_check.pii_sanitized:
                                # PII detectado mas nao blocker: flagear pro cliente via header/metadata.
                                # V1: chunks originais passam (trade-off conhecido — output ja foi
                                # acumulado). V2: reescrever chunks com conteudo sanitizado.
                                context.metadata["output_stream_pii_sanitized"] = True
                            break

                # Flush
                if blocked_by_guard:
                    import json as _json
                    err_payload = _json.dumps({
                        "error": {
                            "message": context.metadata.get("output_stream_block_reason", "Output blocked"),
                            "type": "policy_error",
                            "code": "output_blocked",
                        }
                    })
                    yield f"data: {err_payload}\n\n"
                    yield "data: [DONE]\n\n"
                else:
                    for ck in buffered_chunks:
                        yield ck

                await _pipeline.emit_telemetry(context)

            stream_headers = _build_response_headers(context)
            stream_headers["X-Aion-Decision"] = "passthrough"
            stream_headers["Cache-Control"] = "no-cache"
            stream_headers["Connection"] = "keep-alive"
            _add_contract_headers(stream_headers, contract, mode="transparent")
            return StreamingResponse(
                stream_with_guard(),
                media_type="text/event-stream",
                headers=stream_headers,
            )
        else:
            t0 = time.perf_counter()
            response = await forward_request(effective_request, context, settings)
            llm_latency = (time.perf_counter() - t0) * 1000
            context.module_latencies["llm"] = round(llm_latency, 2)

            # P6: Output guard — S2' (PII) + S3' (risco estrutural) no output do LLM
            if settings.estixe_enabled:
                from aion.shared.contracts import EstixeAction as _EA
                for _mod in _pipeline._pre_modules:
                    if _mod.name == "estixe":
                        _out_text = (
                            (response.choices[0].message.content or "")
                            if response.choices and response.choices[0].message
                            else ""
                        )
                        _out_check = await _mod.check_llm_output(_out_text, context)
                        if _out_check.action == _EA.BLOCK:
                            await _pipeline.emit_telemetry(context)
                            return JSONResponse(
                                status_code=403,
                                content={"error": {
                                    "message": _out_check.block_reason,
                                    "type": "policy_error",
                                    "code": "output_blocked",
                                }},
                                headers=_build_response_headers(context),
                            )
                        if context.metadata.get("filtered_llm_output"):
                            response.choices[0].message.content = (
                                context.metadata.pop("filtered_llm_output")
                            )
                        break

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

            # Record passthrough sample for suggestion engine (opt-in)
            try:
                from aion.config import get_estixe_settings
                from aion.estixe.suggestions import get_suggestion_engine
                from aion.shared.tokens import extract_user_message
                _estixe_settings = get_estixe_settings()
                if _estixe_settings.suggestions_enabled:
                    _user_msg = extract_user_message(effective_request)
                    if _user_msg:
                        _resp_text = (
                            response.choices[0].message.content
                            if response.choices and response.choices[0].message
                            else ""
                        )
                        _cost = context.metadata.get("estimated_cost", 0.0)
                        asyncio.create_task(asyncio.to_thread(
                            get_suggestion_engine().record,
                            context.tenant, _user_msg, len(_resp_text or ""), _cost,
                        ))
            except Exception:
                pass  # suggestion recording is non-critical

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

    # Apply per-tenant runtime overrides to pipeline context (sim customization)
    _tenant_ov = await get_overrides(tenant)
    if "pii_policy" in _tenant_ov:
        context.metadata["pii_policy"] = _tenant_ov["pii_policy"]
    if "estixe_thresholds" in _tenant_ov:
        context.metadata["estixe_thresholds"] = _tenant_ov["estixe_thresholds"]

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
        return _error_response(422, f"Invalid request: {exc}", "validation_error", "invalid_request_error")

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
        return _error_response(422, f"Invalid request: {exc}", "validation_error", "invalid_request_error")

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

    # P7: ESTIXE sub-component health (classifier degradation alert)
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
        # Safe mode takes priority — don't downgrade "safe" to "degraded".
        if health_data.get("mode") == "normal":
            health_data["mode"] = "degraded"

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

    # ── ESTIXE-specific signals (obs panels) ──
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

                # ── DecisionCache (hot path) ──
                dc = health_data.get("decision_cache", {})
                lines.append(f'# HELP aion_decision_cache_hit_rate Hit rate do cache de decisão do pipeline inteiro')
                lines.append(f'# TYPE aion_decision_cache_hit_rate gauge')
                lines.append(f'aion_decision_cache_size{{replica="{replica_id}"}} {dc.get("size", 0)}')
                lines.append(f'aion_decision_cache_hits_total{{replica="{replica_id}"}} {dc.get("hits", 0)}')
                lines.append(f'aion_decision_cache_misses_total{{replica="{replica_id}"}} {dc.get("misses", 0)}')
                lines.append(f'aion_decision_cache_hit_rate{{replica="{replica_id}"}} {dc.get("hit_rate", 0)}')
                lines.append(f'aion_decision_cache_evictions_total{{replica="{replica_id}"}} {dc.get("evictions", 0)}')

                # ── Tier hits (onde decisões são tomadas) ──
                th = health_data.get("tier_hits", {})
                lines.append(f'# HELP aion_tier_hits_total Decisions taken per tier (hot→cold)')
                lines.append(f'# TYPE aion_tier_hits_total counter')
                for tier, count in th.items():
                    lines.append(f'aion_tier_hits_total{{replica="{replica_id}",tier="{tier}"}} {count}')
                break

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


@app.get("/v1/pipeline", tags=["Observability"])
async def pipeline_topology():
    """Retorna a topologia do pipeline: pre-LLM, post-LLM, settings dos modulos.

    Util para debug (inconsistencia tipo 'METIS aparece no log mas nao em active_modules').
    """
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


@app.get("/v1/stats", tags=["Observability"])
async def stats(request: Request):
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    return get_stats(tenant)


@app.get("/v1/events", tags=["Observability"])
async def events(request: Request, limit: int = 100):
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
    # Tenant "default" = visão agregada de todos os tenants (dashboard do console)
    tenant_filter = None if tenant == settings.default_tenant else tenant
    # Usa Redis para cross-replica visibility (fallback local se Redis down)
    from aion.shared.telemetry import get_recent_events_redis
    return await get_recent_events_redis(limit, tenant_filter)


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
    """Reload intents.yaml AND risk_taxonomy.yaml without restart.

    Reloads both SemanticClassifier (intents.yaml) and RiskClassifier (risk_taxonomy.yaml)
    so that seed/example changes take effect immediately.
    """
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            summary = await module.reload()
            return {"status": "reloaded", **summary}
    raise HTTPException(status_code=404, detail="ESTIXE not active")


@app.get("/v1/estixe/suggestions", tags=["Control Plane"])
async def list_suggestions(request: Request):
    """List auto-discovered bypass intent suggestions for tenant."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    try:
        from aion.estixe.suggestions import get_suggestion_engine
        engine = get_suggestion_engine()
        suggestions = engine.generate(tenant)
        return {
            "tenant": tenant,
            "total_samples": engine.tenant_sample_count(tenant),
            "suggestions": [s.to_dict() for s in suggestions],
            "count": len(suggestions),
        }
    except Exception as exc:
        logger.warning("Suggestion generation failed: %s", exc)
        return {"tenant": tenant, "total_samples": 0, "suggestions": [], "count": 0}


@app.post("/v1/estixe/suggestions/{suggestion_id}/approve", tags=["Control Plane"])
async def approve_suggestion(suggestion_id: str, request: Request):
    """Approve a suggestion — marks it for intent creation.

    Returns the intent YAML snippet that the user should add to intents.yaml.
    Body (optional): {"intent_name": "...", "response": "..."}
    """
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    try:
        body = await request.json()
    except Exception:
        body = {}

    from aion.estixe.suggestions import get_suggestion_engine
    engine = get_suggestion_engine()
    existing = next((s for s in engine.generate(tenant) if s.id == suggestion_id), None)
    if not existing:
        return _error_response(404, f"Suggestion '{suggestion_id}' not found", "not_found", "invalid_request")

    intent_name = body.get("intent_name", existing.suggested_intent_name)
    response_text = body.get("response", existing.suggested_response)

    if not engine.approve(tenant, suggestion_id):
        return _error_response(404, f"Suggestion '{suggestion_id}' not found", "not_found", "invalid_request")

    # Build YAML snippet for user to add to intents.yaml
    examples_yaml = "\n".join(f'      - "{msg}"' for msg in existing.sample_messages)
    yaml_snippet = (
        f"{intent_name}:\n"
        f"    action: bypass\n"
        f"    examples:\n{examples_yaml}\n"
        f"    responses:\n"
        f'      - "{response_text}"'
    )

    return {
        "status": "approved",
        "suggestion_id": suggestion_id,
        "intent_name": intent_name,
        "response": response_text,
        "yaml_snippet": yaml_snippet,
        "note": "Adicione este bloco ao config/intents.yaml e chame /v1/estixe/intents/reload",
    }


@app.post("/v1/estixe/suggestions/{suggestion_id}/reject", tags=["Control Plane"])
async def reject_suggestion(suggestion_id: str, request: Request):
    """Reject a suggestion so it doesn't resurface."""
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    from aion.estixe.suggestions import get_suggestion_engine
    get_suggestion_engine().reject(tenant, suggestion_id)
    return {"status": "rejected", "suggestion_id": suggestion_id}


@app.post("/v1/estixe/policies/reload", tags=["Control Plane"])
async def reload_policies():
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            await module._policy.reload()
            return {"status": "reloaded", "rules": module._policy.rule_count}
    raise HTTPException(status_code=404, detail="ESTIXE not active")


@app.post("/v1/estixe/guardrails/reload", tags=["Control Plane"])
async def reload_guardrails():
    """Hot-reload regex PII patterns sem restart.

    Util quando:
      - Dev adiciona novo padrao (cartao virtual, nova PII regional) e quer testar
      - Ajuste de regex exige recompilacao apos edicao do guardrails.py
    """
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            return module._guardrails.reload()
    raise HTTPException(status_code=404, detail="ESTIXE not active")


@app.get("/v1/calibration/{tenant}", tags=["Control Plane"])
async def get_calibration(tenant: str):
    """Shadow mode calibration report for a tenant.

    Returns per-category shadow observation statistics accumulated by NEMOS:
    - Volume, days monitored, confidence mean/std, stability score
    - Promotion readiness across all 4 gates
    - Last promotion timestamp and rollback availability

    Use to decide when to promote, or to detect unstable signals needing more data.
    """
    from aion.config import get_estixe_settings
    from aion.nemos import get_nemos

    estixe_cfg = get_estixe_settings()
    nemos = get_nemos()
    shadow_stats = await nemos.get_shadow_stats(tenant)

    min_requests = estixe_cfg.shadow_promote_min_requests
    min_days = estixe_cfg.shadow_promote_min_days
    max_std = estixe_cfg.shadow_promote_min_stability
    cooldown_days = estixe_cfg.shadow_promote_cooldown_days

    # Current tenant thresholds (to show drift headroom)
    tenant_overrides = await get_overrides(tenant)
    tenant_thresholds: dict = tenant_overrides.get("estixe_thresholds") or {}
    shadow_mode_active = bool(tenant_overrides.get("shadow_mode"))

    categories = []
    ready_count = 0
    for category, obs in shadow_stats.items():
        current_threshold = tenant_thresholds.get(category)
        suggested = obs.suggested_threshold()
        drift_headroom = (
            round(abs(suggested - current_threshold), 3)
            if current_threshold is not None else None
        )
        cooldown_remaining = obs.cooldown_remaining_days(cooldown_days)

        gate_status = {
            "volume": obs.total_seen >= min_requests,
            "time": obs.days_monitored >= min_days,
            "stability": obs.is_stable_enough(max_std),
            "cooldown": cooldown_remaining == 0.0,
        }
        all_gates_pass = all(gate_status.values()) and not obs.promoted

        entry = {
            "category": category,
            "total_seen": obs.total_seen,
            "days_monitored": round(obs.days_monitored, 2),
            "avg_confidence": round(obs.avg_confidence, 4),
            "min_confidence": round(obs.min_confidence, 4),
            "max_confidence": round(obs.max_confidence, 4),
            "confidence_std": round(obs.confidence_std, 4),
            "stability_score": round(obs.stability_score, 3),
            "promoted": obs.promoted,
            "promoted_at": obs.promoted_at or None,
            "rollback_available": obs.promoted and obs.previous_threshold is not None,
            "cooldown_remaining_days": round(cooldown_remaining, 1),
            "current_threshold": current_threshold,
            "suggested_threshold": suggested,
            "drift_headroom": drift_headroom,
            "gates": gate_status,
            "ready_to_promote": all_gates_pass,
        }
        categories.append(entry)
        if all_gates_pass:
            ready_count += 1

    # Sort: ready first, then promoted (under monitoring), then by volume desc
    categories.sort(key=lambda c: (
        -int(c["ready_to_promote"]),
        -int(c["promoted"]),
        -c["total_seen"],
    ))

    # Beacon to ARGOS: anonymized aggregate (fire-and-forget, non-blocking)
    if shadow_stats:
        try:
            from aion.shared.telemetry import beacon_shadow_stats
            asyncio.create_task(beacon_shadow_stats(tenant, shadow_stats))
        except Exception:
            pass

    return {
        "tenant": tenant,
        "shadow_mode_active": shadow_mode_active,
        "promotion_criteria": {
            "min_requests": min_requests,
            "min_days": min_days,
            "max_confidence_std": max_std,
            "cooldown_days": cooldown_days,
            "max_threshold_delta": estixe_cfg.shadow_promote_max_threshold_delta,
        },
        "total_shadow_categories": len(categories),
        "ready_to_promote": ready_count,
        "categories": categories,
    }


@app.get("/v1/calibration/{tenant}/history", tags=["Control Plane"])
async def get_calibration_history(tenant: str):
    """Full promotion/rollback audit trail for all shadow categories of a tenant.

    Returns: {category -> [event, ...]} where each event has:
      event, timestamp, threshold_before, threshold_after,
      observations_count, avg_confidence, confidence_std, stability_score, force
    """
    from aion.nemos import get_nemos
    nemos = get_nemos()
    history = await nemos.get_all_promotion_history(tenant)
    return {
        "tenant": tenant,
        "total_categories_with_history": len(history),
        "history": history,
    }


@app.post("/v1/calibration/{tenant}/promote", tags=["Control Plane"])
async def promote_shadow_category(tenant: str, request: Request):
    """Promote a shadow category to enforcement for a tenant.

    Body: {"category": "social_engineering", "threshold": 0.74, "force": false}
    - threshold optional — defaults to auto-suggested value (avg_confidence * 0.95)
    - force=true bypasses volume/days/stability criteria (not drift control or cooldown)

    Gates applied (in order):
      1. Volume + time: total_seen >= min_requests AND days_monitored >= min_days
      2. Stability: confidence_std <= max_std (signal consistent, not noisy)
      3. Cooldown: days since last promotion >= cooldown_days
      4. Drift: |new_threshold - current_threshold| <= max_delta (no large jumps)

    Effect: writes per-tenant estixe_thresholds override (immediate, no restart).
    Rollback: POST /v1/calibration/{tenant}/rollback {"category": "..."}
    """
    from aion.config import get_estixe_settings
    from aion.nemos import get_nemos

    try:
        body = await request.json()
    except Exception:
        return _error_response(400, "Invalid JSON body", "invalid_json", "invalid_request")

    category = body.get("category")
    if not category:
        return _error_response(400, "Missing required field: category", "missing_field", "invalid_request")

    estixe_cfg = get_estixe_settings()
    nemos = get_nemos()
    obs = await nemos._load_shadow_observation(tenant, category)

    if obs.total_seen == 0:
        return _error_response(
            404,
            f"No shadow observations found for category '{category}' in tenant '{tenant}'",
            "not_found",
            "invalid_request",
        )

    if obs.promoted:
        return _error_response(
            409,
            f"Category '{category}' is already promoted for tenant '{tenant}'",
            "already_promoted",
            "invalid_request",
        )

    force = bool(body.get("force", False))
    gates_failed = []

    # Gate 1 — Volume + time (force=true bypasses)
    min_requests = estixe_cfg.shadow_promote_min_requests
    min_days = estixe_cfg.shadow_promote_min_days
    if not obs.is_promotion_ready(min_requests, min_days):
        gates_failed.append({
            "gate": "volume_and_time",
            "reason": (
                f"Need {min_requests} requests (have {obs.total_seen}) "
                f"and {min_days} days (have {round(obs.days_monitored, 1)})"
            ),
        })

    # Gate 2 — Stability (force=true bypasses)
    max_std = estixe_cfg.shadow_promote_min_stability
    if not obs.is_stable_enough(max_std):
        gates_failed.append({
            "gate": "stability",
            "reason": (
                f"confidence_std={round(obs.confidence_std, 4)} exceeds max={max_std} "
                f"(stability_score={round(obs.stability_score, 3)}). "
                f"Signal needs more consistent observations."
            ),
        })

    if gates_failed and not force:
        return JSONResponse(
            status_code=422,
            content={
                "error": "promotion_criteria_not_met",
                "message": "Use force=true to bypass volume/stability gates (drift and cooldown still apply).",
                "gates_failed": gates_failed,
                "observations": obs.to_dict(),
            },
        )

    # Gate 3 — Cooldown (NOT bypassed by force — prevents rapid re-promotion)
    cooldown_days = estixe_cfg.shadow_promote_cooldown_days
    cooldown_remaining = obs.cooldown_remaining_days(cooldown_days)
    if cooldown_remaining > 0:
        return JSONResponse(
            status_code=429,
            content={
                "error": "promotion_cooldown_active",
                "message": (
                    f"Category '{category}' was promoted recently. "
                    f"Cooldown: {round(cooldown_remaining, 1)} days remaining."
                ),
                "cooldown_days": cooldown_days,
                "remaining_days": round(cooldown_remaining, 1),
            },
        )

    # Resolve threshold: explicit > auto-suggested
    threshold = body.get("threshold")
    threshold = round(float(threshold), 3) if threshold is not None else obs.suggested_threshold()

    # Gate 4 — Drift control (NOT bypassed by force — prevents runaway threshold jumps)
    existing_overrides = await get_overrides(tenant)
    existing_thresholds: dict = existing_overrides.get("estixe_thresholds") or {}
    current_threshold = existing_thresholds.get(category)
    max_delta = estixe_cfg.shadow_promote_max_threshold_delta
    if current_threshold is not None:
        delta = abs(threshold - current_threshold)
        if delta > max_delta:
            clamped = round(current_threshold + (max_delta if threshold > current_threshold else -max_delta), 3)
            return JSONResponse(
                status_code=422,
                content={
                    "error": "threshold_drift_exceeded",
                    "message": (
                        f"Requested threshold {threshold} deviates {round(delta, 3)} from "
                        f"current {current_threshold} (max_delta={max_delta}). "
                        f"Suggested safe value: {clamped}"
                    ),
                    "current_threshold": current_threshold,
                    "requested_threshold": threshold,
                    "max_delta": max_delta,
                    "suggested_threshold": clamped,
                },
            )

    # ── All gates passed — apply promotion ──

    # 1. Write per-tenant threshold override (immediate, no restart)
    existing_thresholds[category] = threshold
    await set_override("estixe_thresholds", existing_thresholds, tenant)

    # 2. Mark promoted in NEMOS (stores previous_threshold for rollback)
    await nemos.mark_shadow_promoted(tenant, category, previous_threshold=current_threshold)

    # 3. Record auditable history event
    history_event = {
        "event": "promote",
        "timestamp": time.time(),
        "threshold_before": current_threshold,
        "threshold_after": threshold,
        "observations_count": obs.total_seen,
        "days_monitored": round(obs.days_monitored, 2),
        "avg_confidence": round(obs.avg_confidence, 4),
        "confidence_std": round(obs.confidence_std, 4),
        "stability_score": round(obs.stability_score, 3),
        "force": force,
        "gates_bypassed": [g["gate"] for g in gates_failed] if force else [],
    }
    await nemos.record_promotion_event(tenant, category, history_event)

    logger.info(
        "SHADOW PROMOTED: tenant='%s' category='%s' threshold=%.3f "
        "(prev=%.3f force=%s std=%.4f stability=%.3f n=%d)",
        tenant, category, threshold,
        current_threshold or 0.0, force,
        obs.confidence_std, obs.stability_score, obs.total_seen,
    )

    return {
        "status": "promoted",
        "tenant": tenant,
        "category": category,
        "threshold_before": current_threshold,
        "threshold_applied": threshold,
        "effect": "immediate — threshold override active via estixe_thresholds",
        "rollback_available": True,
        "persist_note": (
            f"To make permanent, set 'threshold: {threshold}' and remove 'shadow: true' "
            f"from '{category}' in risk_taxonomy.yaml, then POST /v1/estixe/intents/reload"
        ),
        "signal_quality": {
            "observations": obs.total_seen,
            "days_monitored": round(obs.days_monitored, 2),
            "avg_confidence": round(obs.avg_confidence, 4),
            "confidence_std": round(obs.confidence_std, 4),
            "stability_score": round(obs.stability_score, 3),
        },
        "gates_bypassed": history_event["gates_bypassed"],
    }


@app.post("/v1/calibration/{tenant}/rollback", tags=["Control Plane"])
async def rollback_shadow_category(tenant: str, request: Request):
    """Roll back a promoted shadow category to its pre-promotion threshold.

    Body: {"category": "social_engineering"}

    Restores the threshold that was active before the last promotion.
    If no prior threshold existed (taxonomy default), removes the override entirely.
    Records a rollback event in the auditable history.

    After rollback the category re-enters shadow mode — observations keep accumulating.
    """
    from aion.nemos import get_nemos

    try:
        body = await request.json()
    except Exception:
        return _error_response(400, "Invalid JSON body", "invalid_json", "invalid_request")

    category = body.get("category")
    if not category:
        return _error_response(400, "Missing required field: category", "missing_field", "invalid_request")

    nemos = get_nemos()
    obs = await nemos._load_shadow_observation(tenant, category)

    if not obs.promoted:
        return _error_response(
            409,
            f"Category '{category}' is not currently promoted for tenant '{tenant}'",
            "not_promoted",
            "invalid_request",
        )

    previous_threshold = obs.previous_threshold
    existing_overrides = await get_overrides(tenant)
    existing_thresholds: dict = existing_overrides.get("estixe_thresholds") or {}
    current_threshold = existing_thresholds.get(category)

    # Restore or remove threshold
    if previous_threshold is not None:
        existing_thresholds[category] = previous_threshold
    else:
        existing_thresholds.pop(category, None)
    await set_override("estixe_thresholds", existing_thresholds, tenant)

    # Update NEMOS state
    await nemos.mark_shadow_rolled_back(tenant, category)

    # Record rollback event in history
    history_event = {
        "event": "rollback",
        "timestamp": time.time(),
        "threshold_before": current_threshold,
        "threshold_after": previous_threshold,
        "reason": body.get("reason", "manual_rollback"),
    }
    await nemos.record_promotion_event(tenant, category, history_event)

    logger.info(
        "SHADOW ROLLBACK: tenant='%s' category='%s' threshold %.3f → %s",
        tenant, category, current_threshold or 0.0,
        f"{previous_threshold:.3f}" if previous_threshold is not None else "taxonomy_default",
    )

    return {
        "status": "rolled_back",
        "tenant": tenant,
        "category": category,
        "threshold_restored": previous_threshold,
        "effect": (
            "taxonomy default threshold restored"
            if previous_threshold is None
            else f"threshold reverted to {previous_threshold}"
        ),
        "note": "Category is back in shadow mode — observations continue accumulating.",
    }


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

    # Clear suggestion engine samples
    try:
        from aion.estixe.suggestions import get_suggestion_engine
        get_suggestion_engine().delete_tenant(tenant)
    except Exception:
        logger.debug("Suggestion engine delete failed for tenant %s", tenant)

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
