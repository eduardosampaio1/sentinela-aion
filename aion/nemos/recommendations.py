"""Recommendation engine — derives actionable suggestions from NEMOS data.

Recommendations are human-approved changes (not auto-actuation).
They require confidence >= MEDIUM to appear.
"""

from __future__ import annotations

from dataclasses import dataclass

from aion.nemos.ema import SignalConfidence
from aion.nemos.models import IntentMemory, ModelPerformance, OptimizationMemory


@dataclass
class Recommendation:
    type: str          # bypass_candidate | model_switch | policy_tuning | behavior_dial | auto_rollback
    confidence: str    # signal confidence
    reason: str
    estimated_savings_daily: float = 0.0
    details: dict | None = None

    def to_dict(self) -> dict:
        d = {
            "type": self.type,
            "confidence": self.confidence,
            "reason": self.reason,
            "estimated_savings_daily": round(self.estimated_savings_daily, 4),
        }
        if self.details:
            d["details"] = self.details
        return d


def generate_recommendations(
    tenant: str,
    intent_memories: dict[str, IntentMemory],
    model_performances: dict[str, ModelPerformance],
    optimization_memory: OptimizationMemory | None,
) -> list[Recommendation]:
    """Generate recommendations from accumulated NEMOS data."""
    recs: list[Recommendation] = []

    # 1. Bypass candidates — intents with high forward cost and high success
    for intent, mem in intent_memories.items():
        if mem.confidence.value in (SignalConfidence.NONE.value, SignalConfidence.LOW.value):
            continue
        if (
            mem.forwarded_count >= 10
            and mem.bypass_success_rate.value > 0.95
            and mem.avg_cost_when_forwarded.value > 0
        ):
            daily_savings = mem.avg_cost_when_forwarded.value * mem.forwarded_count * 0.1  # rough daily estimate
            recs.append(Recommendation(
                type="bypass_candidate",
                confidence=mem.confidence.value,
                reason=(
                    f"Intent '{intent}': {mem.total_seen} requests, "
                    f"{mem.bypass_success_rate.value:.0%} success rate, "
                    f"avg cost ${mem.avg_cost_when_forwarded.value:.4f} when forwarded"
                ),
                estimated_savings_daily=daily_savings,
                details={"intent": intent, "success_rate": mem.bypass_success_rate.value},
            ))

    # 2. Model switches — models that are expensive for simple intents
    for model_name, perf in model_performances.items():
        if perf.confidence.value in (SignalConfidence.NONE.value, SignalConfidence.LOW.value):
            continue
        simple = perf.by_complexity.get("simple")
        if simple and simple.count >= 10 and simple.avg_cost.value > 0.001:
            recs.append(Recommendation(
                type="model_switch",
                confidence=perf.confidence.value,
                reason=(
                    f"Model '{model_name}' handling {simple.count} simple requests "
                    f"at avg ${simple.avg_cost.value:.4f} — consider routing to cheaper model"
                ),
                estimated_savings_daily=simple.avg_cost.value * simple.count * 0.5 * 0.1,
                details={"model": model_name, "tier": "simple", "count": simple.count},
            ))

    # 3. Compression effectiveness — if METIS compression is hurting
    if optimization_memory and optimization_memory.confidence.value not in (
        SignalConfidence.NONE.value, SignalConfidence.LOW.value
    ):
        compressed_followup = optimization_memory.followup_rate_compressed.value
        uncompressed_followup = optimization_memory.followup_rate_uncompressed.value
        if compressed_followup > uncompressed_followup + 0.1:
            recs.append(Recommendation(
                type="behavior_dial",
                confidence=optimization_memory.confidence.value,
                reason=(
                    f"Compression increases followup rate by "
                    f"{(compressed_followup - uncompressed_followup):.0%} — "
                    f"consider reducing compression aggressiveness"
                ),
                details={
                    "followup_compressed": round(compressed_followup, 3),
                    "followup_uncompressed": round(uncompressed_followup, 3),
                },
            ))

    return recs
