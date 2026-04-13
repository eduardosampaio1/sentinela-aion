"""Router — decides which model to use for each request.

Uses multi-factor scoring: cost × fit × latency × risk × capability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from aion.config import NomosSettings, ScoringWeights
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
    total: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "cost": round(self.cost, 4),
            "fit": round(self.fit, 4),
            "latency": round(self.latency, 4),
            "risk": round(self.risk, 4),
            "capability": round(self.capability, 4),
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
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> RouteDecision:
        """Route request to the best model."""
        # Classify complexity
        messages = [m.model_dump() for m in request.messages]
        complexity = self._classifier.classify(messages)

        # Find models that match this complexity
        candidates = self._registry.get_models_for_complexity(complexity.score)

        if not candidates:
            # Fallback: use any available model
            candidates = self._registry.get_available_models()

        if not candidates:
            # No models available — use the request's original model
            logger.warning("No models available in registry, using request model: %s", request.model)
            return RouteDecision(
                model_name=request.model,
                provider="openai",
                base_url=None,
                complexity_score=complexity.score,
                reason="no_models_available_fallback",
            )

        # Pick the best model
        selected, breakdown, pii_influenced = self._select_best(
            candidates, complexity.score, context,
        )

        return RouteDecision(
            model_name=selected.name,
            provider=selected.provider,
            base_url=selected.base_url,
            complexity_score=complexity.score,
            reason=self._explain(selected, complexity.score, candidates),
            estimated_cost=selected.estimated_cost_per_request,
            score_breakdown=breakdown,
            candidates_evaluated=len(candidates),
            pii_influenced=pii_influenced,
        )

    def _select_best(
        self,
        candidates: list[ModelConfig],
        complexity: float,
        context: PipelineContext,
    ) -> tuple[ModelConfig, Optional[ScoreBreakdown], bool]:
        """Select the best model from candidates using multi-factor scoring."""
        cost_target = context.metadata.get("cost_target")

        if cost_target == "low":
            cheapest = self._registry.get_cheapest(candidates)
            if cheapest:
                return cheapest, None, False

        if cost_target == "fast":
            fastest = self._registry.get_fastest(candidates)
            if fastest:
                return fastest, None, False

        # Multi-factor scoring: lower is better
        pii_detected = bool(context.metadata.get("pii_violations"))
        required_caps = context.metadata.get("required_capabilities", [])
        scored = [
            (m, self._score_multi_factor(m, complexity, pii_detected, required_caps))
            for m in candidates
        ]
        scored.sort(key=lambda x: x[1].total)

        best_model, best_score = scored[0]

        # Did PII influence the decision?
        pii_influenced = False
        if pii_detected and best_score.risk > 0:
            pii_influenced = True
        elif pii_detected and len(scored) > 1:
            # Check if the winner would have been different without risk penalty
            no_risk = [(m, s.total - s.risk) for m, s in scored]
            no_risk.sort(key=lambda x: x[1])
            pii_influenced = no_risk[0][0].name != best_model.name

        return best_model, best_score, pii_influenced

    def _score_multi_factor(
        self,
        model: ModelConfig,
        complexity: float,
        pii_detected: bool,
        required_capabilities: list[str],
    ) -> ScoreBreakdown:
        """Score a model across multiple factors. Lower total = better."""
        w = self._weights

        # 1. Cost
        cost = model.estimated_cost_per_request * w.cost

        # 2. Fit — prefer models whose range center matches complexity
        range_center = (model.complexity_range[0] + model.complexity_range[1]) / 2
        fit = abs(range_center - complexity) * w.fit

        # 3. Latency
        latency = (model.latency_p50_ms / 1000) * w.latency

        # 4. Risk — penalize low-tier models when PII is present
        risk = 0.0
        if pii_detected and model.risk_tier == "low":
            risk = w.risk_penalty

        # 5. Capability match — penalize missing required capabilities
        missing = sum(1 for c in required_capabilities if c not in model.capabilities)
        capability = missing * w.capability_miss

        total = cost + fit + latency + risk + capability
        return ScoreBreakdown(
            cost=cost, fit=fit, latency=latency,
            risk=risk, capability=capability, total=total,
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
