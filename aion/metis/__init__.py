"""METIS — Optimization Engine. Reescreve, comprime, reduz tokens, melhora resposta."""

from __future__ import annotations

import logging

from aion.config import get_metis_settings
from aion.metis.compressor import PromptCompressor
from aion.metis.behavior import BehaviorDial
from aion.metis.optimizer import ResponseOptimizer
from aion.shared.schemas import ChatCompletionRequest, ChatCompletionResponse, PipelineContext

logger = logging.getLogger("aion.metis")


class MetisPreModule:
    """METIS pre-LLM — compresses prompt and applies behavior dial to system prompt."""

    name = "metis"

    def __init__(self) -> None:
        settings = get_metis_settings()
        self._compressor = PromptCompressor(settings)
        self._behavior = BehaviorDial()

    async def process(
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> PipelineContext:
        # Count tokens before
        context.tokens_before = self._compressor.count_tokens(request)

        # Apply behavior dial instructions to system prompt
        behavior = await self._behavior.get(context.tenant)
        if behavior:
            request = self._behavior.apply_to_request(request, behavior)
            context.modified_request = request

        # Compress prompt
        compressed = self._compressor.compress(request)
        context.modified_request = compressed
        context.tokens_after = self._compressor.count_tokens(compressed)

        saved = context.tokens_before - context.tokens_after
        if saved > 0:
            logger.info(
                "METIS compressed: %d → %d tokens (saved %d)",
                context.tokens_before,
                context.tokens_after,
                saved,
            )

        return context


class MetisPostModule:
    """METIS post-LLM — optimizes response based on behavior dial."""

    name = "metis"

    def __init__(self) -> None:
        self._optimizer = ResponseOptimizer()
        self._behavior = BehaviorDial()

    async def process(
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> PipelineContext:
        response = context.metadata.get("llm_response")
        if not response or not isinstance(response, ChatCompletionResponse):
            return context

        behavior = await self._behavior.get(context.tenant)
        if behavior:
            optimized = self._optimizer.optimize(response, behavior)
            context.metadata["llm_response"] = optimized

        return context


_pre_instance = None
_post_instance = None


def get_module() -> MetisPreModule:
    global _pre_instance
    if _pre_instance is None:
        _pre_instance = MetisPreModule()
    return _pre_instance


def get_post_module() -> MetisPostModule:
    global _post_instance
    if _post_instance is None:
        _post_instance = MetisPostModule()
    return _post_instance
