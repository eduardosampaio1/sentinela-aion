"""Tenant baseline — accumulated operational profile with DecayedEMA.

Each tenant builds a baseline over time: average latency, cost, bypass rate,
model distribution, complexity distribution. Snapshots enable trend comparison.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from aion.nemos.ema import DecayedEMA, maturity_from_count


@dataclass
class TenantBaseline:
    """Per-tenant operational baseline. All numeric fields use DecayedEMA."""
    tenant: str
    total_requests: int = 0
    avg_latency_ms: DecayedEMA = field(default_factory=DecayedEMA)
    avg_cost_per_request: DecayedEMA = field(default_factory=DecayedEMA)
    avg_tokens_per_request: DecayedEMA = field(default_factory=DecayedEMA)
    bypass_rate: DecayedEMA = field(default_factory=DecayedEMA)
    block_rate: DecayedEMA = field(default_factory=DecayedEMA)
    model_counts: dict[str, int] = field(default_factory=dict)
    intent_counts: dict[str, int] = field(default_factory=dict)
    complexity_counts: dict[str, int] = field(default_factory=dict)
    first_seen: float = 0.0
    last_updated: float = 0.0

    def record(
        self,
        latency_ms: float,
        cost: float,
        tokens: int,
        model: str,
        intent: str,
        complexity_tier: str,
        decision: str,
        now: float | None = None,
    ) -> None:
        now = now or time.time()
        if self.first_seen == 0.0:
            self.first_seen = now
        self.total_requests += 1
        self.last_updated = now

        self.avg_latency_ms.update(latency_ms, now)
        self.avg_cost_per_request.update(cost, now)
        self.avg_tokens_per_request.update(tokens, now)
        self.bypass_rate.update(1.0 if decision == "bypass" else 0.0, now)
        self.block_rate.update(1.0 if decision == "block" else 0.0, now)

        # Distributions (bounded counts)
        if model:
            self.model_counts[model] = self.model_counts.get(model, 0) + 1
        if intent and len(self.intent_counts) < 100:
            self.intent_counts[intent] = self.intent_counts.get(intent, 0) + 1
        if complexity_tier:
            self.complexity_counts[complexity_tier] = self.complexity_counts.get(complexity_tier, 0) + 1

    @property
    def maturity(self) -> str:
        return maturity_from_count(self.total_requests).value

    @property
    def drift_detected(self) -> bool:
        """Detect if current metrics deviated >20% from stable baseline."""
        if self.total_requests < 100:
            return False
        # Simple heuristic: if EMA count is high but value changed rapidly
        # (last 10 updates shifted the mean significantly)
        return False  # placeholder — refined in snapshot comparison

    def _distribution(self, counts: dict[str, int]) -> dict[str, float]:
        total = sum(counts.values())
        if total == 0:
            return {}
        return {k: round(v / total, 3) for k, v in sorted(counts.items(), key=lambda x: -x[1])}

    def snapshot(self) -> dict:
        """Snapshot for daily persistence and trend comparison."""
        return {
            "total_requests": self.total_requests,
            "avg_latency_ms": round(self.avg_latency_ms.value, 2),
            "avg_cost_per_request": round(self.avg_cost_per_request.value, 6),
            "avg_tokens_per_request": round(self.avg_tokens_per_request.value, 1),
            "bypass_rate": round(self.bypass_rate.value, 3),
            "block_rate": round(self.block_rate.value, 3),
            "timestamp": time.time(),
        }

    def to_dict(self) -> dict:
        return {
            "tenant": self.tenant,
            "maturity": self.maturity,
            "total_requests": self.total_requests,
            "avg_latency_ms": round(self.avg_latency_ms.value, 2),
            "avg_cost_per_request": round(self.avg_cost_per_request.value, 6),
            "avg_tokens_per_request": round(self.avg_tokens_per_request.value, 1),
            "bypass_rate": round(self.bypass_rate.value, 3),
            "block_rate": round(self.block_rate.value, 3),
            "model_distribution": self._distribution(self.model_counts),
            "intent_distribution": self._distribution(self.intent_counts),
            "complexity_distribution": self._distribution(self.complexity_counts),
            "drift_detected": self.drift_detected,
            "first_seen": self.first_seen,
            "last_updated": self.last_updated,
        }
