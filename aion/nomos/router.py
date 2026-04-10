"""Router — decides which model to use for each request."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from aion.nomos.classifier import ComplexityClassifier
from aion.nomos.registry import ModelConfig, ModelRegistry
from aion.shared.schemas import ChatCompletionRequest, PipelineContext

logger = logging.getLogger("aion.nomos.router")


@dataclass
class RouteDecision:
    """Result of routing decision."""
    model_name: str
    provider: str
    base_url: Optional[str]
    complexity_score: float
    reason: str
    estimated_cost: float = 0.0


class Router:
    """Selects the optimal model based on complexity, cost, and availability."""

    def __init__(
        self,
        registry: ModelRegistry,
        classifier: ComplexityClassifier,
    ) -> None:
        self._registry = registry
        self._classifier = classifier

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
        selected = self._select_best(candidates, complexity.score, context)

        return RouteDecision(
            model_name=selected.name,
            provider=selected.provider,
            base_url=selected.base_url,
            complexity_score=complexity.score,
            reason=self._explain(selected, complexity.score, candidates),
            estimated_cost=selected.estimated_cost_per_request,
        )

    def _select_best(
        self,
        candidates: list[ModelConfig],
        complexity: float,
        context: PipelineContext,
    ) -> ModelConfig:
        """Select the best model from candidates using a scoring system."""
        cost_target = context.metadata.get("cost_target")

        if cost_target == "low":
            cheapest = self._registry.get_cheapest(candidates)
            if cheapest:
                return cheapest

        if cost_target == "fast":
            fastest = self._registry.get_fastest(candidates)
            if fastest:
                return fastest

        # Default: balance cost and capability
        # Score each candidate: lower is better
        def score(model: ModelConfig) -> float:
            cost_score = model.estimated_cost_per_request * 10000
            # Prefer models whose complexity range center is closest to actual complexity
            range_center = (model.complexity_range[0] + model.complexity_range[1]) / 2
            fit_score = abs(range_center - complexity) * 0.5
            latency_score = model.latency_p50_ms / 100
            return cost_score + fit_score + latency_score

        candidates.sort(key=score)
        return candidates[0]

    @staticmethod
    def _explain(
        selected: ModelConfig, complexity: float, candidates: list[ModelConfig]
    ) -> str:
        """Generate human-readable explanation of routing decision."""
        if len(candidates) == 1:
            return f"only_available_model"

        if complexity < 30:
            tier = "simple"
        elif complexity < 60:
            tier = "medium"
        else:
            tier = "complex"

        return f"{tier}_prompt→{selected.name}(cost=${selected.estimated_cost_per_request:.6f})"
