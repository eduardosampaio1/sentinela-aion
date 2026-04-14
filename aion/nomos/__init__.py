"""NOMOS — Decision Engine. Escolhe rota, modelo, avalia contexto."""

from __future__ import annotations

import logging

from aion.config import get_nomos_settings
from aion.nomos.classifier import ComplexityClassifier
from aion.nomos.registry import ModelRegistry
from aion.nomos.router import Router
from aion.shared.schemas import ChatCompletionRequest, PipelineContext

logger = logging.getLogger("aion.nomos")


class NomosModule:
    """NOMOS pipeline module — classifies complexity and routes to best model."""

    name = "nomos"

    def __init__(self) -> None:
        self._settings = get_nomos_settings()
        self._registry = ModelRegistry(self._settings)
        self._classifier = ComplexityClassifier()
        self._router = Router(self._registry, self._classifier, self._settings)
        self._initialized = False

    async def initialize(self) -> None:
        if not self._initialized:
            await self._registry.load()
            self._initialized = True
            logger.info("NOMOS initialized with %d models", self._registry.model_count)

    async def process(
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> PipelineContext:
        if not self._initialized:
            await self.initialize()

        # Fetch learned performances from NEMOS (optional, graceful fallback)
        performances = None
        try:
            from aion.nemos import get_nemos
            performances = await get_nemos().get_model_performances(context.tenant)
        except Exception:
            pass  # NEMOS unavailable — route with defaults

        route = self._router.route(request, context, performances=performances)

        context.selected_model = route.model_name
        context.selected_provider = route.provider
        context.selected_base_url = route.base_url
        context.metadata["complexity_score"] = route.complexity_score
        context.metadata["route_reason"] = route.reason
        context.metadata["estimated_cost"] = route.estimated_cost
        context.metadata["candidates_evaluated"] = route.candidates_evaluated
        if route.score_breakdown:
            context.metadata["score_breakdown"] = route.score_breakdown.to_dict()
        if route.pii_influenced:
            context.metadata["pii_influenced_routing"] = True
        if route.confidence:
            context.metadata["decision_confidence"] = route.confidence.to_dict()
        if route.exploration:
            context.metadata["exploration"] = True

        logger.info(
            "NOMOS route: model=%s provider=%s complexity=%.1f reason=%s confidence=%.2f",
            route.model_name,
            route.provider,
            route.complexity_score,
            route.reason,
            route.confidence.score if route.confidence else 0.5,
        )

        return context


_instance = None


def get_module() -> NomosModule:
    global _instance
    if _instance is None:
        _instance = NomosModule()
    return _instance
