"""Formal contracts between AION modules.

Every module MUST produce typed results that conform to these contracts.
This prevents "convention-based" integration and makes the pipeline
formally verifiable.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════
# ESTIXE Contract — what ESTIXE produces
# ══════════════════════════════════════════════

class PiiAction(str, Enum):
    """What to do when a specific PII type is detected."""
    ALLOW = "allow"     # detect but take no action
    MASK = "mask"       # replace with [TYPE_REDACTED]
    BLOCK = "block"     # reject entire request
    AUDIT = "audit"     # allow through but log as violation


class PiiPolicyConfig(BaseModel):
    """Per-tenant PII handling policy."""
    default_action: PiiAction = PiiAction.MASK
    rules: dict[str, PiiAction] = Field(default_factory=dict)  # {"cpf": "allow", "email": "block"}

    def action_for(self, pii_type: str) -> PiiAction:
        """Resolve action for a PII type, falling back to default."""
        return self.rules.get(pii_type, self.default_action)


class EstixeAction(str, Enum):
    CONTINUE = "continue"
    BYPASS = "bypass"
    BLOCK = "block"


class EstixeResult(BaseModel):
    """Formal output of the ESTIXE module."""
    action: EstixeAction = EstixeAction.CONTINUE
    intent_detected: Optional[str] = None
    intent_confidence: float = 0.0
    bypass_response_text: Optional[str] = None
    policy_matched: list[str] = Field(default_factory=list)
    policy_action: Optional[str] = None  # block | transform | flag
    pii_violations: list[str] = Field(default_factory=list)
    pii_sanitized: bool = False
    block_reason: Optional[str] = None


# ══════════════════════════════════════════════
# NOMOS Contract — what NOMOS produces
# ══════════════════════════════════════════════

class NomosResult(BaseModel):
    """Formal output of the NOMOS module."""
    selected_model: str
    selected_provider: str
    base_url: Optional[str] = None
    complexity_score: float = 0.0
    complexity_factors: list[str] = Field(default_factory=list)
    route_reason: str = ""
    estimated_cost: float = 0.0
    fallback_used: bool = False
    fallback_from: Optional[str] = None
    score_breakdown: Optional[dict[str, float]] = None
    candidates_evaluated: int = 0
    pii_influenced: bool = False


# ══════════════════════════════════════════════
# METIS Contract — what METIS produces
# ══════════════════════════════════════════════

class MetisResult(BaseModel):
    """Formal output of the METIS module."""
    tokens_before: int = 0
    tokens_after: int = 0
    tokens_saved: int = 0
    compression_applied: bool = False
    behavior_dial_active: bool = False
    behavior_settings: Optional[dict[str, Any]] = None
    post_optimization_applied: bool = False
    filler_removed: bool = False
    rewrite_applied: bool = False
    rewrite_rule: Optional[str] = None


# ══════════════════════════════════════════════
# Pipeline Decision Record — full trace of what happened
# ══════════════════════════════════════════════

class DecisionRecord(BaseModel):
    """Complete trace of a pipeline decision. Used for explainability."""
    schema_version: str = "1.0"
    request_id: str
    tenant: str
    timestamp: float

    # Final outcome
    decision: str  # continue | bypass | block
    model_used: Optional[str] = None

    # Module results (each module populates its contract)
    estixe: Optional[EstixeResult] = None
    nomos: Optional[NomosResult] = None
    metis: Optional[MetisResult] = None

    # Operational state
    safe_mode: bool = False
    degraded_modules: list[str] = Field(default_factory=list)
    skipped_modules: list[str] = Field(default_factory=list)
    failed_modules: list[str] = Field(default_factory=list)

    # Latencies
    module_latencies_ms: dict[str, float] = Field(default_factory=dict)
    total_pipeline_ms: float = 0.0
    llm_latency_ms: float = 0.0

    # Economics
    tokens_saved: int = 0
    cost_saved: float = 0.0
    cost_estimated: float = 0.0

    # Policy trace
    policies_evaluated: list[str] = Field(default_factory=list)
    policy_that_decided: Optional[str] = None


# ══════════════════════════════════════════════
# RBAC — Role-Based Access Control
# ══════════════════════════════════════════════

class Role(str, Enum):
    ADMIN = "admin"             # full access: killswitch, config, data deletion, key rotation
    OPERATOR = "operator"       # operational: overrides, behavior, module toggle, calibration
    ANALYST = "analyst"         # read + analytics: sessions, budget, compliance
    VIEWER = "viewer"           # read-only: stats, events, audit, health, models
    AUDITOR = "auditor"         # compliance-focused read: audit trail, sessions, reports
    SECURITY = "security"       # security ops: killswitch, policies, threat intel, approvals
    CONSOLE_PROXY = "console_proxy"  # trusted service identity — no own permissions;
                                     # RBAC is enforced via X-Aion-Actor-Role (SSO actor)


# What each role can do
ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.ADMIN: {
        "killswitch:write", "killswitch:read",
        "overrides:write", "overrides:read",
        "behavior:write", "behavior:read",
        "modules:write", "modules:read",
        "estixe:reload", "policies:reload", "policies:write",
        "data:delete",
        "audit:read",
        "stats:read", "events:read", "models:read",
        "budget:write", "budget:read",
        "calibration:promote", "calibration:rollback",
        "approvals:resolve",
        "keys:rotate",
        "collective:read", "collective:install",
    },
    Role.OPERATOR: {
        "overrides:write", "overrides:read",
        "behavior:write", "behavior:read",
        "modules:write", "modules:read",
        "estixe:reload", "policies:reload",
        "audit:read",
        "stats:read", "events:read", "models:read",
        "budget:write", "budget:read",
        "calibration:promote", "calibration:rollback",
        "approvals:resolve",
        "collective:read", "collective:install",
    },
    Role.ANALYST: {
        "overrides:read", "behavior:read", "modules:read",
        "audit:read",
        "stats:read", "events:read", "models:read",
        "budget:read",
        "collective:read",
    },
    Role.VIEWER: {
        "overrides:read", "behavior:read", "modules:read",
        "audit:read",
        "stats:read", "events:read", "models:read",
        "budget:read",
        "collective:read",
    },
    Role.AUDITOR: {
        "audit:read",
        "stats:read", "events:read", "models:read",
        "budget:read",
        "overrides:read", "behavior:read", "modules:read",
        "collective:read",
    },
    Role.SECURITY: {
        "killswitch:write", "killswitch:read",
        "audit:read",
        "stats:read", "events:read", "models:read",
        "overrides:read", "modules:read", "budget:read",
        "approvals:resolve",
        "policies:write",
        "collective:read",
    },
    # console_proxy has NO own permissions — it is a trusted transport, not a human actor.
    # All RBAC enforcement uses the SSO actor role from X-Aion-Actor-Role header.
    Role.CONSOLE_PROXY: set(),
}


def check_permission(role: str, permission: str) -> bool:
    """Check if a role has a specific permission."""
    perms = ROLE_PERMISSIONS.get(role, set())
    return permission in perms


# ══════════════════════════════════════════════
# Policy Precedence
# ══════════════════════════════════════════════

class PolicySource(str, Enum):
    """Where a policy/config came from. Higher = higher priority."""
    DEFAULT = "default"           # hardcoded defaults
    CONFIG_FILE = "config_file"   # YAML files
    TENANT = "tenant"             # tenant-specific config
    OVERRIDE = "override"         # runtime override via API
    REQUEST = "request"           # per-request header override

    @property
    def priority(self) -> int:
        return {
            PolicySource.DEFAULT: 0,
            PolicySource.CONFIG_FILE: 1,
            PolicySource.TENANT: 2,
            PolicySource.OVERRIDE: 3,
            PolicySource.REQUEST: 4,
        }[self]


def resolve_precedence(sources: dict[PolicySource, Any]) -> tuple[Any, PolicySource]:
    """Resolve config value by precedence. Highest priority wins.

    Returns (value, source_that_won).
    """
    winner = PolicySource.DEFAULT
    value = None

    for source, val in sorted(sources.items(), key=lambda x: x[0].priority):
        if val is not None:
            value = val
            winner = source

    return value, winner
