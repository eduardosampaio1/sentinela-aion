"""Proxy router: /v1/chat/completions, /v1/decide, /v1/chat/assisted, /v1/decisions."""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from aion.config import FailMode, get_settings
from aion.middleware import get_overrides
from aion.shared.budget import BudgetExceededError, check_budget
from aion.shared.schemas import ChatCompletionRequest, Decision, PipelineContext

logger = logging.getLogger("aion")

router = APIRouter()

# Streaming timeout (seconds)
_STREAM_TIMEOUT = 300


def _get_pipeline():
    """Get the pipeline from main module (avoids circular import)."""
    import aion.main as _main
    return _main._pipeline


def _error_response(status: int, message: str, code: str, error_type: str = "api_error") -> JSONResponse:
    """OpenAI-compatible error response format."""
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": error_type, "code": code}},
    )


def _build_response_headers(context: PipelineContext) -> dict[str, str]:
    """Build standard response headers for every response."""
    replica_id = os.environ.get("AION_REPLICA_ID", "local")
    _pipeline = _get_pipeline()
    headers = {
        "X-Aion-Decision": context.decision.value if context.decision != Decision.CONTINUE else "passthrough",
        "X-Request-ID": context.request_id,
        "X-Aion-Replica": replica_id,
    }
    if "cache_hit" in context.metadata:
        headers["X-Aion-Cache"] = "HIT" if context.metadata["cache_hit"] else "MISS"
    route_reason = context.metadata.get("route_reason", "")
    if route_reason:
        headers["X-Aion-Route-Reason"] = route_reason.replace("\u2192", "->").encode("latin-1", errors="replace").decode("latin-1")
    pipeline_ms = sum(
        v for k, v in context.module_latencies.items() if k != "llm"
    )
    llm_ms = context.module_latencies.get("llm", 0.0)
    headers["X-Aion-Pipeline-Ms"] = str(round(pipeline_ms, 1))
    if llm_ms:
        headers["X-Aion-Total-Ms"] = str(round(pipeline_ms + llm_ms, 1))
    if _pipeline:
        headers.update(_pipeline.get_degraded_headers())
    return headers


async def _resolve_operating_mode(tenant: str) -> str:
    """Ask NEMOS for the operating_mode; fall back to stateless if unavailable."""
    try:
        from aion.nemos import get_nemos
        return await get_nemos().get_operating_mode(tenant)
    except Exception:
        return "stateless"


def _active_module_names() -> list[str]:
    """Module names that actually ran (for capability reporting)."""
    _pipeline = _get_pipeline()
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


async def _idempotency_lookup(tenant: str, request):
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


async def _record_all_outcomes(context: PipelineContext, response, settings) -> None:
    """Async fire-and-forget: record outcome to NEMOS for all modules."""
    try:
        from aion.nemos import get_nemos
        from aion.nemos.models import OutcomeRecord

        nemos = get_nemos()
        now = time.time()

        prompt_tokens = 0
        completion_tokens = 0
        if hasattr(response, "usage") and response.usage:
            prompt_tokens = response.usage.prompt_tokens or 0
            completion_tokens = response.usage.completion_tokens or 0

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

        if actual_cost > 0:
            try:
                from aion.shared.budget import get_budget_store
                await get_budget_store().record_spend(context.tenant, actual_cost)
            except Exception:
                logger.debug("Budget record_spend failed (non-critical)", exc_info=True)

        try:
            from aion.supabase_writer import write_decision
            pii_violations = context.metadata.get("pii_violations") or []
            pii_count = len(pii_violations) if isinstance(pii_violations, list) else 0
            await write_decision(
                tenant=context.tenant,
                request_id=context.request_id,
                decision=decision,
                model_used=model_name,
                detected_intent=intent,
                complexity_score=complexity,
                risk_category=context.metadata.get("detected_risk_category", ""),
                tokens_input=prompt_tokens,
                tokens_output=completion_tokens,
                cost_actual=actual_cost,
                cost_default=default_cost,
                cost_saved=max(0.0, default_cost - actual_cost),
                pii_detected=pii_count > 0,
                pii_count=pii_count,
                latency_ms=llm_latency,
                cache_hit=bool(context.metadata.get("cache_hit")),
                safe_mode=bool(context.metadata.get("safe_mode")),
                metadata={
                    k: context.metadata[k]
                    for k in ("route_reason", "decision_source", "risk_level")
                    if k in context.metadata
                } or None,
            )
        except Exception:
            logger.debug("Supabase decision write failed (non-critical)", exc_info=True)

    except Exception:
        logger.debug("NEMOS outcome recording failed (non-critical)", exc_info=True)


async def _run_pipeline_and_build_contract(
    chat_request: ChatCompletionRequest,
    tenant: str,
    *,
    settings,
) -> tuple:
    """Shared helper: run pre-LLM pipeline and build the contract."""
    from aion.contract import build_contract
    from aion.pipeline import build_pipeline

    context = PipelineContext(tenant=tenant)
    context.original_request = chat_request
    if not context.modified_request:
        context.modified_request = chat_request

    _tenant_ov = await get_overrides(tenant)
    if "pii_policy" in _tenant_ov:
        context.metadata["pii_policy"] = _tenant_ov["pii_policy"]
    if "estixe_thresholds" in _tenant_ov:
        context.metadata["estixe_thresholds"] = _tenant_ov["estixe_thresholds"]

    import aion.main as _main
    if _main._pipeline is None:
        _main._pipeline = build_pipeline()
    _pipeline = _main._pipeline

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


@router.post("/v1/decide", tags=["Decision Gateway"])
async def decide(request: Request):
    """Pure decision endpoint: retorna CONTINUE/BLOCK/BYPASS SEM chamar LLM."""
    settings = get_settings()
    _pipeline = _get_pipeline()
    if not _pipeline:
        from fastapi import HTTPException
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

    if "pii_policy" in body:
        context.metadata["pii_policy"] = body["pii_policy"]
    if "estixe_thresholds" in body:
        context.metadata["estixe_thresholds"] = body["estixe_thresholds"]

    _decide_ov = await get_overrides(tenant)
    if _decide_ov.get("shadow_mode"):
        context.metadata["shadow_mode"] = True

    for module in _pipeline._pre_modules:
        if module.name == "estixe":
            await module.process(chat_request, context)
            break

    latency = (time.perf_counter() - t0) * 1000
    result = context.estixe_result

    resp = {
        "decision": result.action.value.lower() if result else "continue",
        # bypass_response: pre-crafted reply for bypass decisions (e.g. greetings, FAQ).
        # Present only when decision=="bypass" and a configured response exists.
        # Use this directly — no need to call the LLM.
        "bypass_response": (result.bypass_response_text if result else None),
        "reason": result.block_reason if result else None,
        "detected_intent": result.intent_detected if result else None,
        "confidence": result.intent_confidence if result else None,
        "pii_sanitized": result.pii_sanitized if result else False,
        "metadata": dict(context.metadata),
        "latency_ms": round(latency, 3),
        "source": context.metadata.get("decision_source", "pipeline"),
    }

    headers = {
        "X-Aion-Replica": os.environ.get("AION_REPLICA_ID", "local"),
        "X-Aion-Decision": resp["decision"],
        "X-Aion-Decision-Source": resp["source"],
    }
    return JSONResponse(content=resp, headers=headers)


@router.post("/v1/chat/completions", tags=["LLM Proxy"])
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions endpoint (Transparent mode)."""
    from aion.adapter import get_adapter
    from aion.contract import Action, build_contract
    from aion.pipeline import build_pipeline

    settings = get_settings()

    try:
        body = await request.json()
    except Exception:
        return _error_response(
            400,
            "Invalid request body: malformed JSON or non-UTF-8 encoding",
            "invalid_request",
            "invalid_request_error",
        )

    messages = body.get("messages", [])
    if len(messages) > 100:
        return _error_response(400, "Too many messages (max 100)", "too_many_messages", "invalid_request")

    try:
        chat_request = ChatCompletionRequest(**body)
    except Exception as e:
        return _error_response(422, f"Invalid request format: {e}", "validation_error", "invalid_request_error")

    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    idemp_key, cached = await _idempotency_lookup(tenant, request)
    if cached and cached.response:
        headers = {"X-Request-ID": cached.contract.request_id}
        _add_contract_headers(headers, cached.contract, mode="transparent", idempotent_hit=True)
        return JSONResponse(content=cached.response, headers=headers)

    context = PipelineContext(tenant=tenant)
    context.original_request = chat_request
    if not context.modified_request:
        context.modified_request = chat_request
    if idemp_key:
        context.metadata["idempotency_key"] = idemp_key

    if settings.multi_turn_context and chat_request.messages:
        from aion.shared.turn_context import derive_session_id
        _explicit_sid = request.headers.get("X-Aion-Session-Id") or None
        context.session_id = derive_session_id(tenant, chat_request.messages, explicit_id=_explicit_sid)

    _tenant_ov = await get_overrides(tenant)
    if "pii_policy" in _tenant_ov:
        context.metadata["pii_policy"] = _tenant_ov["pii_policy"]
    if "estixe_thresholds" in _tenant_ov:
        context.metadata["estixe_thresholds"] = _tenant_ov["estixe_thresholds"]
    if _tenant_ov.get("shadow_mode"):
        context.metadata["shadow_mode"] = True

    import aion.main as _main
    if _main._pipeline is None:
        _main._pipeline = build_pipeline()
    _pipeline = _main._pipeline

    t_pipeline = time.perf_counter()
    try:
        context = await _pipeline.run_pre(chat_request, context)
    except Exception:
        logger.exception("Pipeline pre-LLM failed (request_id=%s)", context.request_id)
        if settings.fail_mode == FailMode.CLOSED:
            return _error_response(503, "AION pipeline error (fail-closed)", "pipeline_error")
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

    effective_request = context.modified_request or chat_request

    try:
        await check_budget(tenant, context)
    except BudgetExceededError as _budget_err:
        return _error_response(
            429,
            f"Budget cap reached: {_budget_err.cap_type} spend ${_budget_err.spend:.4f} >= cap ${_budget_err.cap:.4f}",
            "budget_exceeded",
            "rate_limit_error",
        )
    except Exception:
        pass  # fail-open

    try:
        if chat_request.stream:
            async def stream_with_guard():
                buffered_chunks: list[str] = []
                accumulated_content: list[str] = []

                try:
                    async with asyncio.timeout(_STREAM_TIMEOUT):
                        import aion.main as _main_module
                        _fwd_stream = _main_module.forward_request_stream
                        async for chunk in _fwd_stream(
                            effective_request, context, settings
                        ):
                            buffered_chunks.append(chunk)
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
                                        pass
                except asyncio.TimeoutError:
                    logger.warning("Stream timeout after %ds (request_id=%s)", _STREAM_TIMEOUT, context.request_id)

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
                                context.metadata["output_stream_pii_sanitized"] = True
                            break

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
            import aion.main as _main_module
            response = await _main_module.forward_request(effective_request, context, settings)
            llm_latency = (time.perf_counter() - t0) * 1000
            context.module_latencies["llm"] = round(llm_latency, 2)

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

            asyncio.create_task(_record_all_outcomes(context, response, settings))

            try:
                from aion.cache import get_cache
                _cache = get_cache()
                if _cache.enabled:
                    asyncio.create_task(asyncio.to_thread(
                        _cache.store, effective_request, response, context
                    ))
            except Exception:
                pass

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
                pass

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


@router.post("/v1/chat/assisted", tags=["LLM Proxy"])
async def chat_assisted(request: Request):
    """Assisted mode — AION executa, retorna response + DecisionContract."""
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

    _pipeline = _get_pipeline()
    await _pipeline.emit_telemetry(context)

    if contract.action == Action.BLOCK:
        headers = _build_response_headers(context)
        _add_contract_headers(headers, contract, mode="assisted")
        return JSONResponse(
            status_code=403,
            content={"response": None, "contract": contract.model_dump()},
            headers=headers,
        )

    adapter = get_adapter()
    t_exec = time.perf_counter()
    result = await adapter.execute(contract, stream=False)
    execution_latency_ms = (time.perf_counter() - t_exec) * 1000

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


@router.post("/v1/decisions", tags=["LLM Proxy"])
async def decisions(request: Request):
    """Decision mode — AION decide, nao executa. Retorna DecisionContract cru."""
    settings = get_settings()
    body = await request.json()

    if len(body.get("messages", [])) > 100:
        return _error_response(400, "Too many messages (max 100)", "too_many_messages", "invalid_request")

    try:
        chat_request = ChatCompletionRequest(**body)
    except Exception as exc:
        return _error_response(422, f"Invalid request: {exc}", "validation_error", "invalid_request_error")

    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

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

    _pipeline = _get_pipeline()
    await _pipeline.emit_telemetry(context)

    headers = _build_response_headers(context)
    _add_contract_headers(headers, contract, mode="decision")

    contract.meta.metrics.execution_latency_ms = 0.0
    contract.meta.metrics.total_latency_ms = contract.meta.metrics.decision_latency_ms

    await _idempotency_store(tenant, idemp_key, contract, response_dict=None, executed=False)
    return JSONResponse(content=contract.model_dump(), headers=headers)
