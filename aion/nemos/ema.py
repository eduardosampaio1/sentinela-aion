"""DecayedEMA — Exponential Moving Average with temporal decay.

Core primitive for all NEMOS learning. Values naturally lose relevance
over time (half-life 7 days), and the learning rate adapts based on
data volume (fast when cold, stable when mature).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class SignalConfidence(str, Enum):
    """Confidence level based on data volume."""
    NONE = "none"      # no data — signal ignored, use defaults
    LOW = "low"        # <20 data points — signal ignored
    MEDIUM = "medium"  # 20-100 data points — signal at 50% weight
    HIGH = "high"      # 100+ data points — signal at full weight


def confidence_from_count(count: int) -> SignalConfidence:
    if count <= 0:
        return SignalConfidence.NONE
    if count < 20:
        return SignalConfidence.LOW
    if count < 100:
        return SignalConfidence.MEDIUM
    return SignalConfidence.HIGH


def confidence_weight(confidence: SignalConfidence) -> float:
    """Weight multiplier for a signal based on its confidence."""
    return {
        SignalConfidence.NONE: 0.0,
        SignalConfidence.LOW: 0.0,
        SignalConfidence.MEDIUM: 0.5,
        SignalConfidence.HIGH: 1.0,
    }[confidence]


class ModuleMaturityState(str, Enum):
    COLD = "cold"      # <20 requests
    WARM = "warm"      # 20-100 requests
    STABLE = "stable"  # 100+ requests


def maturity_from_count(count: int) -> ModuleMaturityState:
    if count < 20:
        return ModuleMaturityState.COLD
    if count < 100:
        return ModuleMaturityState.WARM
    return ModuleMaturityState.STABLE


@dataclass
class DecayedEMA:
    """Exponential Moving Average with temporal decay.

    - Half-life: after ``half_life_hours`` of inactivity, the stored
      value decays to 50 % of its weight.
    - Adaptive alpha: starts high (0.30) when data is scarce and
      converges to 0.01 as data accumulates.
    """

    value: float = 0.0
    count: int = 0
    last_update: float = 0.0
    half_life_hours: float = 168.0  # 7 days

    def update(self, new_value: float, now: float | None = None) -> None:
        now = now or time.time()

        if self.count == 0:
            # First observation — seed directly
            self.value = new_value
            self.count = 1
            self.last_update = now
            return

        # Temporal decay
        age_hours = max(0, (now - self.last_update) / 3600)
        decay = 0.5 ** (age_hours / self.half_life_hours) if self.half_life_hours > 0 else 1.0

        # Adaptive learning rate
        effective_alpha = max(0.01, min(0.3, 1.0 / (self.count + 1)))

        self.value = effective_alpha * new_value + (1 - effective_alpha) * (self.value * decay)
        self.count += 1
        self.last_update = now

    @property
    def confidence(self) -> SignalConfidence:
        return confidence_from_count(self.count)

    def to_dict(self) -> dict:
        return {
            "value": round(self.value, 6),
            "count": self.count,
            "last_update": self.last_update,
            "confidence": self.confidence.value,
        }

    @classmethod
    def from_dict(cls, data: dict, half_life_hours: float = 168.0) -> DecayedEMA:
        return cls(
            value=data.get("value", 0.0),
            count=data.get("count", 0),
            last_update=data.get("last_update", 0.0),
            half_life_hours=half_life_hours,
        )


@dataclass
class TierStats:
    """Aggregated stats for a complexity tier (simple/medium/complex)."""
    count: int = 0
    avg_latency: DecayedEMA = field(default_factory=DecayedEMA)
    avg_cost: DecayedEMA = field(default_factory=DecayedEMA)
    success_rate: DecayedEMA = field(default_factory=lambda: DecayedEMA(value=1.0))

    def record(self, latency_ms: float, cost: float, success: bool, now: float | None = None) -> None:
        now = now or time.time()
        self.count += 1
        self.avg_latency.update(latency_ms, now)
        self.avg_cost.update(cost, now)
        self.success_rate.update(1.0 if success else 0.0, now)

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "avg_latency": self.avg_latency.to_dict(),
            "avg_cost": self.avg_cost.to_dict(),
            "success_rate": self.success_rate.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> TierStats:
        return cls(
            count=data.get("count", 0),
            avg_latency=DecayedEMA.from_dict(data.get("avg_latency", {})),
            avg_cost=DecayedEMA.from_dict(data.get("avg_cost", {})),
            success_rate=DecayedEMA.from_dict(data.get("success_rate", {"value": 1.0})),
        )
