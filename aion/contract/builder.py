"""Contract builder — consumes PipelineContext and produces DecisionContract.

The builder is the single place where ``context`` + module results are
translated into the standardized contract. Executors and HTTP handlers
never build contracts themselves — always via ``build_contract``.
"""

from __future__ import annotations

import time
from typing import Optional

from aion.contract.capabilities import Capabilities, CapabilityState
from aion.contract.decision import (
    Action,
    ContractMeta,
    ContractMetrics,
    DecisionConfidence,
    DecisionContract,
    FinalOutput,
    default_retry_policy,
    target_type_for,
)
from aion.contract.errors import ContractError, ErrorType
from aion.shared.schemas import Decision, PipelineContext


def _decision_to_action(context: PipelineContext) -> Action:
    """Map the pipeline's Decision enum to a contract Action."""
    if context.decision == Decision.BLOCK:
        return Action.BLOCK
    if context.decision == Decision.BYPASS:
        return Action.BYPASS
    # CONTINUE — needs to be executed by an Adapter
    # Default is CALL_LLM; CALL_SERVICE is chosen by policy (future hook).
    if context.metadata.get("call_service_name"):
        return Action.CALL_SERVICE
    if context.metadata.get("approval_required"):
        return Action.REQUEST_HUMAN_APPROVAL
    return Action.CALL_LLM


def _build_final_output(context: PipelineContext, action: Action) -> Optional[FinalOutput]:
    """Build the Adapter-facing payload for a given action."""
    target = target_type_for(action)

    if action == Action.CALL_LLM:
        request = context.modified_request or context.original_request
        payload = {
            "provider": context.selected_provider or "openai",
            "model": context.selected_model or "",
            "base_url": context.selected_base_url,
            "request_payload": request.model_dump(exclude_none=True) if request else {},
        }
    elif action == Action.CALL_SERVICE:
        payload = {
            "service_name": context.metadata.get("call_service_name"),
            "endpoint": context.metadata.get("service_endpoint"),
            "method": context.metadata.get("service_method", "POST"),
            "body": context.metadata.get("service_body", {}),
            "headers": context.metadata.get("service_headers", {}),
        }
    elif action == Action.BYPASS or action == Action.RETURN_RESPONSE:
        payload = {
            "response": context.bypass_response.model_dump() if context.bypass_response else None,
        }
    elif action == Action.BLOCK:
        payload = {
            "reason": context.metadata.get("block_reason", "Request blocked by policy"),
            "policy_that_decided": context.metadata.get("policy_that_decided"),
        }
    elif action == Action.REQUEST_HUMAN_APPROVAL:
        # Populated by approval policy (v1: minimal placeholder)
        payload = context.metadata.get("approval_payload", {})
    else:
        payload = {}

    return FinalOutput(
        target_type=target,
        payload=payload,
        retry_policy=default_retry_policy(target),
    )


def _build_capabilities(context: PipelineContext, active_modules: list[str]) -> Capabilities:
    """Report which capabilities ran for this request.

    Maps module names to capability roles:
    - estixe → control
    - nomos  → routing
    - metis  → optimization
    NEMOS is NOT a capability (implicit via operating_mode).
    """
    caps = Capabilities()

    # Control (ESTIXE)
    if "estixe" in active_modules:
        caps.control = CapabilityState(applied=True)
    else:
        caps.control = CapabilityState(skipped=True, reason="disabled")

    # Routing (NOMOS)
    if "nomos" in active_modules:
        caps.routing = CapabilityState(applied=True)
    else:
        caps.routing = CapabilityState(skipped=True, reason="disabled")

    # Optimization (METIS)
    if "metis" in active_modules:
        caps.optimization = CapabilityState(applied=True)
    else:
        caps.optimization = CapabilityState(skipped=True, reason="disabled")

    # Mark failed modules
    for failed in context.metadata.get("failed_modules", []) or []:
        role = {"estixe": "control", "nomos": "routing", "metis": "optimization"}.get(failed)
        if role:
            setattr(caps, role, CapabilityState(applied=False, failed=True, reason="degraded"))

    return caps


def _build_confidence(context: PipelineContext) -> DecisionConfidence:
    """Extract DecisionConfidence from context metadata."""
    dc = context.metadata.get("decision_confidence", {})
    if isinstance(dc, dict) and dc:
        score = float(dc.get("score", 0.5))
        factors = list(dc.get("factors", []))
        maturity = dc.get("maturity", "cold")
    else:
        score = 0.5
        factors = ["heuristic"]
        maturity = "cold"
    # DecisionConfidence validator derives level from score
    return DecisionConfidence(score=score, factors=factors, maturity=maturity)


def _build_error(context: PipelineContext) -> Optional[ContractError]:
    """Extract a ContractError from context if the pipeline blocked or failed."""
    if context.decision == Decision.BLOCK:
        return ContractError(
            type=ErrorType.POLICY_VIOLATION,
            retryable=False,
            detail=context.metadata.get("block_reason"),
        )
    return None


def build_contract(
    context: PipelineContext,
    *,
    active_modules: Optional[list[str]] = None,
    operating_mode: str = "stateless",
    decision_latency_ms: float = 0.0,
    execution_latency_ms: float = 0.0,
    tokens_used: int = 0,
    cost_usd: float = 0.0,
    environment: str = "prod",
) -> DecisionContract:
    """Build a DecisionContract from a PipelineContext.

    Single canonical place to translate internal pipeline state to the
    external contract. Called by HTTP handlers after pipeline runs.
    """
    action = _decision_to_action(context)

    metrics = ContractMetrics(
        decision_latency_ms=round(decision_latency_ms, 2),
        execution_latency_ms=round(execution_latency_ms, 2),
        total_latency_ms=round(decision_latency_ms + execution_latency_ms, 2),
        tokens_used=tokens_used,
        cost_usd=round(cost_usd, 6),
        nemos_mode=operating_mode,
    )

    meta = ContractMeta(
        tenant=context.tenant,
        environment=environment,  # type: ignore[arg-type]
        timestamp=time.time(),
        trace_id=context.metadata.get("trace_id"),
        metrics=metrics,
    )

    return DecisionContract(
        request_id=context.request_id,
        idempotency_key=context.metadata.get("idempotency_key"),
        action=action,
        final_output=_build_final_output(context, action),
        capabilities=_build_capabilities(context, active_modules or []),
        operating_mode=operating_mode,  # type: ignore[arg-type]
        decision_confidence=_build_confidence(context),
        error=_build_error(context),
        meta=meta,
    )
