"""Router — decides which model to use for each request.

Uses multi-factor scoring: cost × fit × latency × risk × capability × learned.
The ``learned`` factor substitutes static estimates with real observed data
from NEMOS (DecayedEMA). Exploration vs exploitation ensures the system
doesn't get stuck in a local optimum.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Optional

from aion.config import NomosSettings, ScoringWeights
from aion.nemos.ema import SignalConfidence, confidence_weight
from aion.nemos.models import DecisionConfidence, ModelPerformance
from aion.nomos.classifier import ComplexityClassifier
from aion.nomos.registry import ModelConfig, ModelRegistry
from aion.shared.schemas import ChatCompletionRequest, PipelineContext

logger = logging.getLogger("aion.nomos.router")


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of multi-factor model score."""
    cost: float = 0.0
    fit: float = 0.0
    latency: float = 0.0
    risk: float = 0.0
    capability: float = 0.0
    learned: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "cost": round(self.cost, 4),
            "fit": round(self.fit, 4),
            "latency": round(self.latency, 4),
            "risk": round(self.risk, 4),
            "capability": round(self.capability, 4),
            "learned": round(self.learned, 4),
            "total": round(self.total, 4),
        }


@dataclass
class RouteDecision:
    """Result of routing decision."""
    model_name: str
    provider: str
    base_url: Optional[str]
    complexity_score: float
    reason: str
    estimated_cost: float = 0.0
    score_breakdown: Optional[ScoreBreakdown] = None
    candidates_evaluated: int = 0
    pii_influenced: bool = False
    confidence: Optional[DecisionConfidence] = None
    exploration: bool = False


class Router:
    """Selects the optimal model based on complexity, cost, risk, and capabilities."""

    def __init__(
        self,
        registry: ModelRegistry,
        classifier: ComplexityClassifier,
        settings: Optional[NomosSettings] = None,
    ) -> None:
        self._registry = registry
        self._classifier = classifier
        self._weights = (settings.scoring_weights if settings else ScoringWeights())

    def route(
        self,
        request: ChatCompletionRequest,
        context: PipelineContext,
        performances: dict[str, ModelPerformance] | None = None,
        complexity_floor: float = 0.0,
    ) -> RouteDecision:
        """Route request to the best model."""
        # Classify complexity
        messages = [m.model_dump() for m in request.messages]
        complexity = self._classifier.classify(messages)

        # Multi-turn: don't downgrade model for follow-ups to complex turns
        effective_complexity = max(complexity.score, complexity_floor)
        if effective_complexity > complexity.score:
            logger.debug(
                "Complexity floor applied: %.3f → %.3f (multi-turn)", complexity.score, effective_complexity
            )

        # Find models that match this complexity
        candidates = self._registry.get_models_for_complexity(effective_complexity)

        if not candidates:
            candidates = self._registry.get_available_models()

        if not candidates:
            logger.warning("No models available in registry, using request model: %s", request.model)
            return RouteDecision(
                model_name=request.model,
                provider="openai",
                base_url=None,
                complexity_score=effective_complexity,
                reason="no_models_available_fallback",
            )

        # Pick the best model
        selected, breakdown, pii_influenced, is_exploration = self._select_best(
            candidates, effective_complexity, context, performances,
        )

        # Compute decision confidence
        confidence = self._compute_confidence(
            selected, performances, context,
        )

        return RouteDecision(
            model_name=selected.name,
            provider=selected.provider,
            base_url=selected.base_url,
            complexity_score=effective_complexity,
            reason=self._explain(selected, effective_complexity, candidates),
            estimated_cost=selected.estimated_cost_per_request,
            score_breakdown=breakdown,
            candidates_evaluated=len(candidates),
            pii_influenced=pii_influenced,
            confidence=confidence,
            exploration=is_exploration,
        )

    def _select_best(
        self,
        candidates: list[ModelConfig],
        complexity: float,
        context: PipelineContext,
        performances: dict[str, ModelPerformance] | None = None,
    ) -> tuple[ModelConfig, Optional[ScoreBreakdown], bool, bool]:
        """Select the best model. Returns (model, breakdown, pii_influenced, is_exploration)."""
        cost_target = context.metadata.get("cost_target")

        if cost_target == "low":
            cheapest = self._registry.get_cheapest(candidates)
            if cheapest:
                return cheapest, None, False, False

        if cost_target == "fast":
            fastest = self._registry.get_fastest(candidates)
            if fastest:
                return fastest, None, False, False

        # Multi-factor scoring: lower is better
        pii_detected = bool(context.metadata.get("pii_violations"))
        required_caps = context.metadata.get("required_capabilities", [])
        scored = [
            (m, self._score_multi_factor(
                m, complexity, pii_detected, required_caps,
                performances.get(m.name) if performances else None,
                context,
            ))
            for m in candidates
        ]
        scored.sort(key=lambda x: x[1].total)

        best_model, best_score = scored[0]

        # Exploration vs exploitation
        is_exploration = False
        exploration_rate = self._exploration_rate(best_score, context)
        if len(scored) >= 3 and random.random() < exploration_rate:
            # Pick randomly among top-3 (not just the best)
            selected_idx = random.randint(0, min(2, len(scored) - 1))
            best_model, best_score = scored[selected_idx]
            is_exploration = True

        # Did PII influence the decision?
        pii_influenced = False
        if pii_detected and best_score.risk > 0:
            pii_influenced = True
        elif pii_detected and len(scored) > 1:
            no_risk = [(m, s.total - s.risk) for m, s in scored]
            no_risk.sort(key=lambda x: x[1])
            pii_influenced = no_risk[0][0].name != best_model.name

        return best_model, best_score, pii_influenced, is_exploration

    def _score_multi_factor(
        self,
        model: ModelConfig,
        complexity: float,
        pii_detected: bool,
        required_capabilities: list[str],
        perf: ModelPerformance | None = None,
        context: PipelineContext | None = None,
    ) -> ScoreBreakdown:
        """Score a model across multiple factors. Lower total = better.

        The ``learned`` factor substitutes static estimates with real data
        observed via NEMOS. Capped at ±15% of the base score to prevent
        historical data from dominating when stale or scarce.
        """
        w = self._weights

        # 1. Cost
        cost = model.estimated_cost_per_request * w.cost

        # 2. Fit
        range_center = (model.complexity_range[0] + model.complexity_range[1]) / 2
        fit = abs(range_center - complexity) * w.fit

        # 3. Latency
        latency = (model.latency_p50_ms / 1000) * w.latency

        # 4. Risk
        risk = 0.0
        if pii_detected and model.risk_tier == "low":
            risk = w.risk_penalty

        # 5. Capability match
        missing = sum(1 for c in required_capabilities if c not in model.capabilities)
        capability = missing * w.capability_miss

        # 6. Learned — real observed data from NEMOS (Decision → Outcome → Recalibration)
        learned = 0.0
        if perf and perf.request_count >= 10:
            tier = "simple" if complexity < 30 else "medium" if complexity < 60 else "complex"
            tier_stats = perf.by_complexity.get(tier)

            perf_weight = confidence_weight(perf.confidence)

            if tier_stats and tier_stats.count >= 5:
                # A) Latency drift: real vs declared
                real_lat = tier_stats.avg_latency.value
                declared_lat = model.latency_p50_ms
                if declared_lat > 0:
                    drift = (real_lat - declared_lat) / declared_lat
                    if drift > 0.3:
                        learned += drift * 10.0 * perf_weight
                    elif drift < -0.2:
                        learned -= abs(drift) * 3.0 * perf_weight

                # B) Reliability
                if tier_stats.success_rate.value < 0.95:
                    learned += (1.0 - tier_stats.success_rate.value) * 100.0 * perf_weight

                # C) Cost correction
                est_cost = model.estimated_cost_per_request
                if tier_stats.avg_cost.value > 0 and est_cost > 0:
                    cost_drift = tier_stats.avg_cost.value / est_cost
                    if cost_drift > 1.3:
                        learned += (cost_drift - 1.0) * w.cost * 0.1 * perf_weight

            # D) Per-intent learning
            detected = context.metadata.get("detected_intent") if context else None
            if detected and detected in perf.by_intent:
                intent_stats = perf.by_intent[detected]
                if intent_stats.count >= 3 and intent_stats.success_rate.value < 0.9:
                    learned += 15.0 * perf_weight

        # Cap learned at ±15% of base score
        base_score = cost + fit + latency + risk + capability
        max_learned = base_score * 0.15
        learned = max(-max_learned, min(max_learned, learned)) * w.learned

        total = base_score + learned
        return ScoreBreakdown(
            cost=cost, fit=fit, latency=latency,
            risk=risk, capability=capability,
            learned=learned, total=total,
        )

    def _exploration_rate(self, best_score: ScoreBreakdown, context: PipelineContext) -> float:
        """Adaptive exploration rate based on decision confidence."""
        # Higher confidence → less exploration
        # This is a rough approximation; real confidence comes from _compute_confidence
        if best_score.learned != 0:
            return 0.05  # has learned data → standard 5%
        return 0.10  # cold → explore more (10%)

    def _compute_confidence(
        self,
        selected: ModelConfig,
        performances: dict[str, ModelPerformance] | None,
        context: PipelineContext,
    ) -> DecisionConfidence:
        """Compute composite confidence for the routing decision."""
        score = 0.5  # base: heuristic
        factors = ["heuristic"]
        maturity = "cold"

        if performances:
            perf = performances.get(selected.name)
            if perf and perf.confidence in (SignalConfidence.MEDIUM, SignalConfidence.HIGH):
                score += 0.15
                factors.append("model_performance")
                maturity = perf.maturity.value

        if context.metadata.get("detected_intent"):
            score += 0.10
            factors.append("intent_detected")

        if context.metadata.get("pii_violations"):
            score += 0.05
            factors.append("pii_aware")

        return DecisionConfidence(
            score=min(1.0, score),
            factors=factors,
            maturity=maturity,
        )

    @staticmethod
    def _explain(
        selected: ModelConfig, complexity: float, candidates: list[ModelConfig]
    ) -> str:
        """Generate human-readable explanation of routing decision."""
        if len(candidates) == 1:
            return "only_available_model"

        if complexity < 30:
            tier = "simple"
        elif complexity < 60:
            tier = "medium"
        else:
            tier = "complex"

        return f"{tier}_prompt→{selected.name}(cost=${selected.estimated_cost_per_request:.6f})"
