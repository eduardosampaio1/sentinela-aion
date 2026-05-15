"""KAIROS data models — Policy Lifecycle Manager contracts.

LLM-AGNOSTIC INVARIANT
----------------------
No model, field, or template in KAIROS may contain a physical provider or model ID
(e.g. gpt-4o, claude, gemini, azure_openai_deployment).

Any model reference must use one of:
  - ModelTierRef(type="model_tier", value="low_cost_fast")
  - ModelTierRef(type="model_alias", value="customer_default_model")
  - ModelTierRef(type="capability", value="safe_response")

NOMOS (local, per-customer) resolves aliases to physical providers.
KAIROS governs policies — it never selects or calls a provider.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class PolicyCandidateStatus(str, Enum):
    DRAFT = "draft"
    READY_FOR_SHADOW = "ready_for_shadow"
    SHADOW_RUNNING = "shadow_running"
    SHADOW_COMPLETED = "shadow_completed"
    APPROVED_PRODUCTION = "approved_production"
    UNDER_REVIEW = "under_review"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class ActionType(str, Enum):
    BYPASS_LLM = "bypass_llm"
    ROUTE_TO_API = "route_to_api"
    ROUTE_TO_MODEL = "route_to_model"
    BLOCK = "block"
    HANDOFF = "handoff"
    ASK_CLARIFICATION = "ask_clarification"
    COMPRESS_CONTEXT = "compress_context"


class FallbackType(str, Enum):
    MODEL_TIER = "model_tier"
    MODEL_ALIAS = "model_alias"
    CAPABILITY = "capability"
    HUMAN_HANDOFF = "human_handoff"
    SAFE_RESPONSE = "safe_response"
    NONE = "none"


class LifecycleActorType(str, Enum):
    SYSTEM = "system"
    OPERATOR = "operator"
    SWEEP = "sweep"


class ShadowRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Sub-models ───────────────────────────────────────────────────────────────


class ModelTierRef(BaseModel):
    """LLM-agnostic model reference. NOMOS resolves to physical provider."""

    type: Literal["model_tier", "model_alias", "capability"]
    value: str
    # Allowed values: low_cost_fast | high_reasoning | customer_default_model |
    #                 customer_fast_model | customer_reasoning_model | safe_response


class TriggerCondition(BaseModel):
    field: str
    operator: Literal["equals", "not_equals", "gte", "lte", "contains", "in", "matches_pattern"]
    value: Union[str, float, bool, list[str]]
    description: str = ""


class ProposedAction(BaseModel):
    action_type: ActionType
    target: Optional[str] = None             # API endpoint name (route_to_api)
    model_ref: Optional[ModelTierRef] = None  # model reference (route_to_model)
    response_template: Optional[str] = None  # template key (bypass_llm)
    reason: Optional[str] = None             # reason code (block)
    description: str = ""


class FallbackStrategy(BaseModel):
    type: FallbackType
    value: Optional[str] = None  # model tier value when type=model_tier/alias
    conditions: list[str] = []
    description: str = ""


class PolicyThreshold(BaseModel):
    name: str
    value: float
    unit: Optional[str] = None
    description: str = ""


class SuccessCriterion(BaseModel):
    metric: str
    operator: Literal["gte", "lte", "equals"]
    target_value: float
    window: str
    description: str = ""


class EvidenceRef(BaseModel):
    artifact_type: str
    artifact_id: str
    source_module: str
    relevance_score: float = 0.0
    summary: str = ""


class EstimatedImpact(BaseModel):
    affected_interactions: Optional[int] = None
    estimated_cost_avoided_monthly: Optional[float] = None
    estimated_tokens_saved_monthly: Optional[int] = None
    estimated_latency_reduction_ms: Optional[float] = None
    estimated_handoff_delta_pct: Optional[float] = None
    estimated_fallback_delta_pct: Optional[float] = None


# ── Core models ───────────────────────────────────────────────────────────────


class PolicyTemplate(BaseModel):
    """A reusable policy blueprint. Instantiated into a PolicyCandidate."""

    id: str
    vertical: str
    type: str
    title: str
    description: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"
    trigger: dict[str, Any] = Field(default_factory=dict)
    action: dict[str, Any] = Field(default_factory=dict)
    fallback: dict[str, Any] = Field(default_factory=dict)
    exclusions: list[str] = []
    default_thresholds: list[dict[str, Any]] = []
    default_success_criteria: list[dict[str, Any]] = []


class PolicyCandidate(BaseModel):
    """A policy hypothesis ready for governance review and shadow testing."""

    id: str
    tenant_id: str
    template_id: Optional[str] = None
    type: str
    status: PolicyCandidateStatus = PolicyCandidateStatus.DRAFT
    title: str
    business_summary: str
    technical_summary: str = ""
    trigger_conditions: list[TriggerCondition] = []
    proposed_actions: list[ProposedAction] = []
    fallback_strategy: Optional[FallbackStrategy] = None
    exclusions: list[str] = []
    thresholds: list[PolicyThreshold] = []
    success_criteria: list[SuccessCriterion] = []
    estimated_impact: Optional[EstimatedImpact] = None
    evidence_refs: list[EvidenceRef] = []
    created_at: str = Field(default_factory=lambda: _now_iso())
    updated_at: str = Field(default_factory=lambda: _now_iso())
    shadow_run_id: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejection_reason: Optional[str] = None


class LifecycleEvent(BaseModel):
    """Immutable audit record for a PolicyCandidate state transition."""

    id: str
    candidate_id: str
    tenant_id: str
    from_status: Optional[str] = None
    to_status: str
    actor_id: Optional[str] = None
    actor_type: LifecycleActorType
    reason: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: _now_iso())


class ShadowRun(BaseModel):
    """Tracks a shadow mode execution for a PolicyCandidate."""

    id: str
    candidate_id: str
    tenant_id: str
    status: ShadowRunStatus = ShadowRunStatus.RUNNING
    started_at: str = Field(default_factory=lambda: _now_iso())
    completed_at: Optional[str] = None
    observations_count: int = 0
    matched_count: int = 0
    fallback_count: int = 0
    estimated_cost_avoided: Optional[float] = None
    summary: Optional[dict[str, Any]] = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
