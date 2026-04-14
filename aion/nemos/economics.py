"""Runtime Economics — cost breakdown by model, intent, decision, time period."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EconomicsBucket:
    """Aggregated economics for a tenant in a time period."""
    tenant: str
    period: str  # "2026-04-14", "2026-04-W16", "2026-04"

    total_requests: int = 0
    total_actual_cost: float = 0.0
    total_default_cost: float = 0.0  # what it would have cost without AION routing
    total_savings: float = 0.0

    by_model: dict[str, ModelBucketEntry] = field(default_factory=dict)
    by_intent: dict[str, IntentBucketEntry] = field(default_factory=dict)
    by_decision: dict[str, int] = field(default_factory=dict)

    def record(
        self,
        model: str,
        intent: str,
        decision: str,
        actual_cost: float,
        default_cost: float,
        tokens: int,
        latency_ms: float,
    ) -> None:
        self.total_requests += 1
        self.total_actual_cost += actual_cost
        self.total_default_cost += default_cost
        self.total_savings += max(0, default_cost - actual_cost)

        # By decision
        self.by_decision[decision] = self.by_decision.get(decision, 0) + 1

        # By model (bounded to 20)
        if model and (model in self.by_model or len(self.by_model) < 20):
            if model not in self.by_model:
                self.by_model[model] = ModelBucketEntry(model=model)
            self.by_model[model].record(actual_cost, default_cost, tokens, latency_ms)

        # By intent (bounded to 50)
        if intent and (intent in self.by_intent or len(self.by_intent) < 50):
            if intent not in self.by_intent:
                self.by_intent[intent] = IntentBucketEntry(intent=intent)
            self.by_intent[intent].record(actual_cost, tokens)

    def to_dict(self) -> dict:
        return {
            "tenant": self.tenant,
            "period": self.period,
            "summary": {
                "total_requests": self.total_requests,
                "total_actual_cost": round(self.total_actual_cost, 6),
                "total_default_cost": round(self.total_default_cost, 6),
                "total_savings": round(self.total_savings, 6),
                "savings_percentage": round(
                    (self.total_savings / self.total_default_cost * 100) if self.total_default_cost > 0 else 0, 1
                ),
            },
            "by_model": {k: v.to_dict() for k, v in self.by_model.items()},
            "by_intent": {k: v.to_dict() for k, v in self.by_intent.items()},
            "by_decision": self.by_decision,
        }


@dataclass
class ModelBucketEntry:
    model: str
    requests: int = 0
    total_cost: float = 0.0
    total_default_cost: float = 0.0
    total_tokens: int = 0
    total_latency_ms: float = 0.0

    def record(self, cost: float, default_cost: float, tokens: int, latency_ms: float) -> None:
        self.requests += 1
        self.total_cost += cost
        self.total_default_cost += default_cost
        self.total_tokens += tokens
        self.total_latency_ms += latency_ms

    def to_dict(self) -> dict:
        return {
            "requests": self.requests,
            "cost": round(self.total_cost, 6),
            "savings_vs_default": round(max(0, self.total_default_cost - self.total_cost), 6),
            "avg_latency_ms": round(self.total_latency_ms / self.requests, 1) if self.requests else 0,
        }


@dataclass
class IntentBucketEntry:
    intent: str
    requests: int = 0
    total_cost: float = 0.0
    total_tokens: int = 0

    def record(self, cost: float, tokens: int) -> None:
        self.requests += 1
        self.total_cost += cost
        self.total_tokens += tokens

    def to_dict(self) -> dict:
        return {
            "requests": self.requests,
            "cost": round(self.total_cost, 6),
            "avg_cost": round(self.total_cost / self.requests, 6) if self.requests else 0,
        }
