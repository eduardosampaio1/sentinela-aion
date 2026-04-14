"""NEMOS data models — structures for decision memory, intent memory, optimization memory."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from aion.nemos.ema import (
    DecayedEMA,
    ModuleMaturityState,
    SignalConfidence,
    TierStats,
    confidence_from_count,
    maturity_from_count,
)


# ══════════════════════════════════════════════
# NOMOS: Decision Memory
# ══════════════════════════════════════════════


@dataclass
class OutcomeRecord:
    """Single request outcome — emitted async after LLM response."""
    request_id: str
    tenant: str
    timestamp: float
    model: str
    provider: str
    complexity_score: float
    detected_intent: str
    estimated_cost: float
    actual_cost: float
    actual_latency_ms: float
    actual_prompt_tokens: int
    actual_completion_tokens: int
    success: bool
    route_reason: str
    decision: str  # "continue" | "bypass" | "block"


@dataclass
class ModelPerformance:
    """Aggregated model performance per tenant. Updated via DecayedEMA."""
    model: str
    tenant: str
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    by_complexity: dict[str, TierStats] = field(default_factory=dict)
    by_intent: dict[str, TierStats] = field(default_factory=dict)
    updated_at: float = 0.0

    def record(
        self,
        complexity_tier: str,
        intent: str,
        latency_ms: float,
        cost: float,
        success: bool,
        now: float | None = None,
    ) -> None:
        now = now or time.time()
        self.request_count += 1
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        self.updated_at = now

        # By complexity tier
        if complexity_tier not in self.by_complexity:
            self.by_complexity[complexity_tier] = TierStats()
        self.by_complexity[complexity_tier].record(latency_ms, cost, success, now)

        # By intent (cap at 50 distinct intents to bound memory)
        if intent and (intent in self.by_intent or len(self.by_intent) < 50):
            if intent not in self.by_intent:
                self.by_intent[intent] = TierStats()
            self.by_intent[intent].record(latency_ms, cost, success, now)

    @property
    def confidence(self) -> SignalConfidence:
        return confidence_from_count(self.request_count)

    @property
    def maturity(self) -> ModuleMaturityState:
        return maturity_from_count(self.request_count)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "tenant": self.tenant,
            "request_count": self.request_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "confidence": self.confidence.value,
            "maturity": self.maturity.value,
            "by_complexity": {k: v.to_dict() for k, v in self.by_complexity.items()},
            "by_intent": {k: v.to_dict() for k, v in self.by_intent.items()},
            "updated_at": self.updated_at,
        }


# ══════════════════════════════════════════════
# ESTIXE: Intent & Policy Intelligence
# ══════════════════════════════════════════════


@dataclass
class IntentMemory:
    """Per-tenant per-intent learning. Tracks bypass effectiveness."""
    intent: str
    total_seen: int = 0
    bypassed_count: int = 0
    forwarded_count: int = 0
    bypass_success_rate: DecayedEMA = field(default_factory=lambda: DecayedEMA(value=1.0))
    avg_cost_when_forwarded: DecayedEMA = field(default_factory=DecayedEMA)
    followup_rate: DecayedEMA = field(default_factory=DecayedEMA)

    def record_bypass(self, was_correct: bool, now: float | None = None) -> None:
        now = now or time.time()
        self.total_seen += 1
        self.bypassed_count += 1
        self.bypass_success_rate.update(1.0 if was_correct else 0.0, now)

    def record_forward(self, cost: float, had_followup: bool, now: float | None = None) -> None:
        now = now or time.time()
        self.total_seen += 1
        self.forwarded_count += 1
        self.avg_cost_when_forwarded.update(cost, now)
        self.followup_rate.update(1.0 if had_followup else 0.0, now)

    @property
    def confidence(self) -> SignalConfidence:
        return confidence_from_count(self.total_seen)

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "total_seen": self.total_seen,
            "bypassed_count": self.bypassed_count,
            "forwarded_count": self.forwarded_count,
            "bypass_success_rate": self.bypass_success_rate.to_dict(),
            "avg_cost_when_forwarded": self.avg_cost_when_forwarded.to_dict(),
            "followup_rate": self.followup_rate.to_dict(),
            "confidence": self.confidence.value,
        }


@dataclass
class PolicyStats:
    """Per-policy effectiveness tracking."""
    policy_name: str
    times_triggered: int = 0
    false_positive_suspicion: DecayedEMA = field(default_factory=DecayedEMA)
    cost_saved: DecayedEMA = field(default_factory=DecayedEMA)

    def record_trigger(self, was_false_positive: bool, cost_impact: float, now: float | None = None) -> None:
        now = now or time.time()
        self.times_triggered += 1
        self.false_positive_suspicion.update(1.0 if was_false_positive else 0.0, now)
        self.cost_saved.update(cost_impact, now)

    def to_dict(self) -> dict:
        return {
            "policy_name": self.policy_name,
            "times_triggered": self.times_triggered,
            "false_positive_suspicion": self.false_positive_suspicion.to_dict(),
            "cost_saved": self.cost_saved.to_dict(),
        }


# ══════════════════════════════════════════════
# METIS: Optimization Intelligence
# ══════════════════════════════════════════════


@dataclass
class OptimizationMemory:
    """Per-tenant compression/optimization learning."""
    tenant: str
    total: int = 0
    compression_effectiveness: DecayedEMA = field(default_factory=DecayedEMA)
    avg_tokens_saved: DecayedEMA = field(default_factory=DecayedEMA)
    followup_rate_compressed: DecayedEMA = field(default_factory=DecayedEMA)
    followup_rate_uncompressed: DecayedEMA = field(default_factory=DecayedEMA)

    def record(
        self,
        tokens_before: int,
        tokens_after: int,
        compression_applied: bool,
        had_followup: bool,
        now: float | None = None,
    ) -> None:
        now = now or time.time()
        self.total += 1

        tokens_saved = tokens_before - tokens_after
        self.avg_tokens_saved.update(tokens_saved, now)

        if compression_applied and tokens_before > 0:
            reduction_pct = tokens_saved / tokens_before
            self.compression_effectiveness.update(reduction_pct, now)
            self.followup_rate_compressed.update(1.0 if had_followup else 0.0, now)
        else:
            self.followup_rate_uncompressed.update(1.0 if had_followup else 0.0, now)

    @property
    def confidence(self) -> SignalConfidence:
        return confidence_from_count(self.total)

    def to_dict(self) -> dict:
        return {
            "tenant": self.tenant,
            "total": self.total,
            "compression_effectiveness": self.compression_effectiveness.to_dict(),
            "avg_tokens_saved": self.avg_tokens_saved.to_dict(),
            "followup_rate_compressed": self.followup_rate_compressed.to_dict(),
            "followup_rate_uncompressed": self.followup_rate_uncompressed.to_dict(),
            "confidence": self.confidence.value,
        }


# ══════════════════════════════════════════════
# Economics
# ══════════════════════════════════════════════


@dataclass
class EconomicSignals:
    """Derived signals from economics that drive routing and policy."""
    model_cost_correction: dict[str, float] = field(default_factory=dict)
    intent_best_model: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "model_cost_correction": self.model_cost_correction,
            "intent_best_model": self.intent_best_model,
        }


# ══════════════════════════════════════════════
# Decision Confidence
# ══════════════════════════════════════════════


@dataclass
class DecisionConfidence:
    """Composite confidence for a routing decision."""
    score: float = 0.5
    factors: list[str] = field(default_factory=lambda: ["heuristic"])
    maturity: str = "cold"

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 2),
            "factors": self.factors,
            "maturity": self.maturity,
        }
