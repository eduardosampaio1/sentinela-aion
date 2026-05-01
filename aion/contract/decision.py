"""DecisionContract — the standardized output of the AION core.

AION padroniza a decisao, nao a execucao. Este arquivo define o
contrato que AION emite — consumido pelo ExecutionAdapter (Transparent/
Assisted) ou retornado cru (Decision mode).
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from aion.contract.capabilities import Capabilities
from aion.contract.errors import ContractError

logger = logging.getLogger("aion.contract")


# ══════════════════════════════════════════════
# Action + side effect
# ══════════════════════════════════════════════


class Action(str, Enum):
    """Intention decided by AION."""
    CALL_LLM = "CALL_LLM"
    CALL_SERVICE = "CALL_SERVICE"
    BYPASS = "BYPASS"
    BLOCK = "BLOCK"
    RETURN_RESPONSE = "RETURN_RESPONSE"
    REQUEST_HUMAN_APPROVAL = "REQUEST_HUMAN_APPROVAL"


class SideEffectLevel(str, Enum):
    """Operational risk of the action."""
    NONE = "none"          # no observable external side-effect
    EXTERNAL = "external"  # external system affected (API, DB write, email)
    HUMAN = "human"        # human approval flow


_ACTION_TO_SIDE_EFFECT: dict[Action, SideEffectLevel] = {
    Action.CALL_LLM: SideEffectLevel.NONE,
    Action.CALL_SERVICE: SideEffectLevel.EXTERNAL,
    Action.BYPASS: SideEffectLevel.NONE,
    Action.BLOCK: SideEffectLevel.NONE,
    Action.RETURN_RESPONSE: SideEffectLevel.NONE,
    Action.REQUEST_HUMAN_APPROVAL: SideEffectLevel.HUMAN,
}

_ACTION_TO_TARGET_TYPE: dict[Action, str] = {
    Action.CALL_LLM: "llm",
    Action.CALL_SERVICE: "service",
    Action.BYPASS: "direct",
    Action.BLOCK: "direct",
    Action.RETURN_RESPONSE: "direct",
    Action.REQUEST_HUMAN_APPROVAL: "human",
}


def side_effect_for(action: Action) -> SideEffectLevel:
    return _ACTION_TO_SIDE_EFFECT[action]


def target_type_for(action: Action) -> str:
    return _ACTION_TO_TARGET_TYPE[action]


# ══════════════════════════════════════════════
# Decision confidence
# ══════════════════════════════════════════════


class ConfidenceLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DecisionConfidence(BaseModel):
    """Composite confidence for a routing/decision outcome.

    ``level`` is ALWAYS derived from ``score`` via the validator below —
    never set manually. ``score`` is the single source of truth.
    """
    score: float = 0.5
    level: ConfidenceLevel = ConfidenceLevel.LOW
    factors: list[str] = Field(default_factory=list)
    maturity: Literal["cold", "warm", "stable"] = "cold"

    @model_validator(mode="after")
    def derive_level(self) -> "DecisionConfidence":
        if self.score >= 0.75:
            self.level = ConfidenceLevel.HIGH
        elif self.score >= 0.5:
            self.level = ConfidenceLevel.MEDIUM
        elif self.score > 0:
            self.level = ConfidenceLevel.LOW
        else:
            self.level = ConfidenceLevel.NONE
        return self


# ══════════════════════════════════════════════
# Retry policy (explicit in contract)
# ══════════════════════════════════════════════


class RetryPolicy(BaseModel):
    max_retries: int = 3
    timeout_ms: int = 30000
    backoff_base_ms: int = 1000
    backoff_max_ms: int = 10000
    retryable_errors: list[str] = Field(default_factory=lambda: ["timeout", "upstream_error"])


def default_retry_policy(target_type: str) -> Optional[RetryPolicy]:
    if target_type == "llm":
        return RetryPolicy(max_retries=3, timeout_ms=30000)
    if target_type == "service":
        return RetryPolicy(max_retries=2, timeout_ms=5000)
    return None  # direct/human dont retry


# ══════════════════════════════════════════════
# Final output (minimum contract)
# ══════════════════════════════════════════════


class FinalOutput(BaseModel):
    """Envelope for the Adapter. Shape stable; payload varies by target_type.

    payload_schema_version evolves independently from contract_version.
    """
    target_type: Literal["llm", "service", "direct", "human"]
    payload: dict = Field(default_factory=dict)
    payload_schema_version: str = "1.0"
    retry_policy: Optional[RetryPolicy] = None


# ══════════════════════════════════════════════
# Provenance (F-22 — replay anchors)
# ══════════════════════════════════════════════


class RequestProvenance(BaseModel):
    """Cryptographic + version anchors that make a decision replayable.

    F-22: in Decision-Only mode the contract IS the product. Without these
    fields, an auditor reviewing a decision 30 days later cannot reconstruct
    why AION decided what it did — they only see the final action and the
    bypass response (if any), not the inputs and policies that produced it.

    All fields are optional so the contract version bump is non-breaking;
    older callers ignoring `provenance` continue to work.
    """
    # SHA-256 (hex) of the original request payload as received by AION.
    # Lets the auditor confirm "yes, this is the exact request the customer
    # claims to have sent" without storing the prompt itself.
    original_request_hash: Optional[str] = None
    # Hash of the request post-METIS compression (only populated when METIS
    # actually changed the payload; otherwise None).
    modified_request_hash: Optional[str] = None
    # tokens_after / tokens_before (when METIS ran). 1.0 means no compression.
    compression_ratio: Optional[float] = None
    # Version strings from the YAMLs that drove the decision. Operators bump
    # these whenever they change rules, so a contract referencing "1.0" can
    # be replayed against a 1.0 snapshot of the YAMLs even after a 1.1 deploy.
    policy_version: Optional[str] = None
    intents_version: Optional[str] = None
    models_version: Optional[str] = None
    # Hash of the merged system prompt at decision time (when applicable).
    prompt_template_hash: Optional[str] = None


# ══════════════════════════════════════════════
# Metrics + Meta
# ══════════════════════════════════════════════


class ContractMetrics(BaseModel):
    decision_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0
    nemos_mode: str = "stateless"

    @model_validator(mode="after")
    def validate_total(self) -> "ContractMetrics":
        expected = self.decision_latency_ms + self.execution_latency_ms
        drift = abs(self.total_latency_ms - expected)
        if drift > 0.01:
            from aion.config import get_settings
            env = getattr(get_settings(), "environment", "prod")
            if env in ("dev", "staging"):
                logger.error(
                    "ContractMetrics total_latency drift=%.3fms in env=%s: total=%.3f vs expected=%.3f",
                    drift, env, self.total_latency_ms, expected,
                )
                raise ValueError(f"total_latency_ms inconsistent (drift={drift:.3f}ms)")
            logger.warning(
                "ContractMetrics total_latency auto-corrected: %.3f -> %.3f",
                self.total_latency_ms, expected,
            )
            self.total_latency_ms = expected
        return self


class ExtensionEntry(BaseModel):
    """Metadata envelope for a single entry in ``meta.extensions``."""
    value: Any
    stage: Literal["experimental", "beta", "deprecated"]
    added_version: str
    deprecated_in: Optional[str] = None
    replaces: Optional[str] = None


class ContractMeta(BaseModel):
    tenant: str
    environment: Literal["prod", "staging", "dev"] = "prod"
    timestamp: float = 0.0
    trace_id: Optional[str] = None
    metrics: ContractMetrics = Field(default_factory=ContractMetrics)
    extensions: dict[str, ExtensionEntry] = Field(default_factory=dict)


# ══════════════════════════════════════════════
# DecisionContract (top-level envelope)
# ══════════════════════════════════════════════


class DecisionContract(BaseModel):
    """The unified output of AION core.

    Emitted once per request. Consumed by the ExecutionAdapter (Transparent
    and Assisted modes) or returned as-is (Decision mode).
    """
    contract_version: str = "1.1"  # F-22: added `provenance`
    request_id: str
    idempotency_key: Optional[str] = None

    action: Action
    side_effect_level: SideEffectLevel = SideEffectLevel.NONE  # derived in validator
    final_output: Optional[FinalOutput] = None

    capabilities: Capabilities = Field(default_factory=Capabilities)
    operating_mode: Literal["stateless", "learning", "adaptive", "stabilized"] = "stateless"
    decision_confidence: DecisionConfidence = Field(default_factory=DecisionConfidence)

    # F-22: replay anchors. Optional so existing callers continue to work.
    provenance: Optional[RequestProvenance] = None

    error: Optional[ContractError] = None
    meta: ContractMeta

    @model_validator(mode="after")
    def derive_side_effect(self) -> "DecisionContract":
        # side_effect_level is always derived from action
        self.side_effect_level = side_effect_for(self.action)
        return self
