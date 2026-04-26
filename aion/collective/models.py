"""Data models for the AION Collective editorial exchange."""

from __future__ import annotations

import time
from typing import Literal, Optional

from pydantic import BaseModel, Field


class PolicyProvenance(BaseModel):
    """Lineage and audit trail for a Collective editorial policy."""
    version: str
    last_updated: str           # ISO date string, e.g. "2026-04-18"
    author: str                 # "AION Editorial" in Phase 1
    signed_by_aion: bool
    changelog: list[str] = []   # most-recent-first list of change notes


class CollectivePolicyMetrics(BaseModel):
    """Aggregated performance metrics for an editorial policy."""
    installs_production: int = 0
    avg_savings_pct: float = 0.0        # 0.0 when not applicable (security policies)
    avg_latency_change_ms: float = 0.0  # negative = improvement
    false_positive_rate: float = 0.0
    rollback_rate: float = 0.0
    confidence_score: float = 0.0


class CollectivePolicy(BaseModel):
    """An editorial policy published in the AION Collective Exchange."""
    id: str
    name: str
    description: str
    sectors: list[str]                                           # ["banking", "fintech", ...]
    editorial: bool = True                                       # Phase 1: always True
    risk_level: Literal["low", "medium", "high"] = "low"
    reversible: bool = True
    provenance: PolicyProvenance
    metrics: CollectivePolicyMetrics = Field(default_factory=CollectivePolicyMetrics)
    # Populated at request-time for the authenticated tenant — None if not installed
    installed_status: Optional[Literal["sandbox", "shadow", "production"]] = None


class InstalledCollectivePolicy(BaseModel):
    """Record of a Collective policy installed by a tenant."""
    policy_id: str
    tenant: str
    status: Literal["sandbox", "shadow", "production"] = "sandbox"
    installed_at: float = Field(default_factory=time.time)
    version: str = ""
