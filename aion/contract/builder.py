"""Contract builder — consumes PipelineContext and produces DecisionContract.

The builder is the single place where ``context`` + module results are
translated into the standardized contract. Executors and HTTP handlers
never build contracts themselves — always via ``build_contract``.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Optional

from aion.contract.capabilities import Capabilities, CapabilityState
from aion.contract.decision import (
    Action,
    ContractMeta,
    ContractMetrics,
    DecisionConfidence,
    DecisionContract,
    FinalOutput,
    RequestProvenance,
    default_retry_policy,
    target_type_for,
)
from aion.contract.errors import ContractError, ErrorType
from aion.shared.schemas import Decision, PipelineContext

logger = logging.getLogger("aion.contract.builder")


# ── F-22: YAML version cache (loaded once, refreshed on hot-reload) ──────────
# Operators reload YAMLs via /v1/estixe/intents/reload etc. — we read the
# file once here per-process and let the operator clear the cache via
# clear_provenance_cache() if they want to re-derive after a hot-reload.
_yaml_version_cache: dict[str, Optional[str]] = {}


def _read_yaml_version(path: Path) -> Optional[str]:
    """Extract the top-level `version: "..."` from a YAML file.

    We scan for the first non-comment line that starts with `version:` —
    avoids importing the full YAML loader for a single-line lookup.
    """
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("version:"):
                    val = line.split(":", 1)[1].strip()
                    # strip surrounding quotes if any
                    if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                        val = val[1:-1]
                    return val or None
                # First non-version, non-comment line — version field absent.
                break
    except Exception as exc:
        logger.debug("YAML version read failed for %s: %s", path, exc)
    return None


def _yaml_version_cached(key: str, path: Path) -> Optional[str]:
    if key not in _yaml_version_cache:
        _yaml_version_cache[key] = _read_yaml_version(path)
    return _yaml_version_cache[key]


def clear_provenance_cache() -> None:
    """Clear the YAML version cache. Call after hot-reload of any policy/intents/models YAML."""
    _yaml_version_cache.clear()


def _hash_request(request_obj) -> Optional[str]:
    """SHA-256 of the request payload JSON (None if unavailable)."""
    if request_obj is None:
        return None
    try:
        # Pydantic v2: model_dump_json with deterministic ordering for hash stability.
        payload = request_obj.model_dump_json(exclude_none=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    except Exception as exc:
        logger.debug("Request hash failed: %s", exc)
        return None


def _hash_system_prompts(request_obj) -> Optional[str]:
    """SHA-256 of merged system messages (the "prompt template" used at decision time)."""
    if request_obj is None or not getattr(request_obj, "messages", None):
        return None
    try:
        sys_parts: list[str] = []
        for m in request_obj.messages:
            role = getattr(m, "role", "")
            if role == "system":
                content = getattr(m, "content", "") or ""
                sys_parts.append(str(content))
        if not sys_parts:
            return None
        merged = "\n".join(sys_parts)
        return hashlib.sha256(merged.encode("utf-8")).hexdigest()
    except Exception as exc:
        logger.debug("System prompt hash failed: %s", exc)
        return None


def _build_provenance(context: PipelineContext) -> RequestProvenance:
    """F-22: build the replay-anchors block for the contract.

    Hashes are computed defensively — if any field fails to compute, we leave
    it as None rather than aborting the contract. The presence of partial
    provenance is still strictly better than the previous "no provenance" state.
    """
    try:
        from aion.config import get_settings
        cfg_dir = Path(get_settings().config_dir)
    except Exception:
        cfg_dir = Path("config")

    # Original request hash — pre-pipeline payload.
    original_hash = _hash_request(context.original_request)

    # Modified request hash — only if METIS (or anyone) actually changed the payload.
    modified_hash: Optional[str] = None
    if context.modified_request is not None and context.modified_request is not context.original_request:
        candidate = _hash_request(context.modified_request)
        if candidate and candidate != original_hash:
            modified_hash = candidate

    # Compression ratio — only when METIS actually counted tokens.
    compression_ratio: Optional[float] = None
    tb = getattr(context, "tokens_before", 0) or 0
    ta = getattr(context, "tokens_after", 0) or 0
    if tb > 0 and ta > 0:
        compression_ratio = round(ta / tb, 4)

    # Prompt template hash — system messages only (the "instructions" anchor).
    prompt_hash = _hash_system_prompts(context.original_request)

    return RequestProvenance(
        original_request_hash=original_hash,
        modified_request_hash=modified_hash,
        compression_ratio=compression_ratio,
        policy_version=_yaml_version_cached("policies", cfg_dir / "policies.yaml"),
        intents_version=_yaml_version_cached(
            "intents",
            Path(__file__).resolve().parent.parent / "estixe" / "data" / "intents.yaml",
        ),
        models_version=_yaml_version_cached("models", cfg_dir / "models.yaml"),
        prompt_template_hash=prompt_hash,
    )


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
        provenance=_build_provenance(context),  # F-22
        error=_build_error(context),
        meta=meta,
    )
