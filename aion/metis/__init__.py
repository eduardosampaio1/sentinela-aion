"""METIS — Optimization Engine. Reescreve, comprime, reduz tokens, melhora resposta."""

from __future__ import annotations

import logging

from aion.config import get_metis_settings
from aion.metis.compressor import PromptCompressor
from aion.metis.behavior import BehaviorDial
from aion.metis.optimizer import ResponseOptimizer
from aion.shared.contracts import MetisResult
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

        # Check NEMOS for optimization memory (optional, graceful fallback)
        compression_ok = True
        try:
            from aion.nemos import get_nemos
            opt_mem = await get_nemos().get_optimization_memory(context.tenant)
            if opt_mem and opt_mem.total >= 20:
                # If compression is causing more followups than not compressing, back off
                compressed_followup = opt_mem.followup_rate_compressed.value
                uncompressed_followup = opt_mem.followup_rate_uncompressed.value
                if compressed_followup > uncompressed_followup + 0.15:
                    compression_ok = False
                    logger.info(
                        "METIS: compression backed off for tenant '%s' "
                        "(compressed followup %.0f%% vs uncompressed %.0f%%)",
                        context.tenant,
                        compressed_followup * 100,
                        uncompressed_followup * 100,
                    )
        except Exception:
            pass  # NEMOS unavailable — compress as normal

        # Apply behavior dial instructions to system prompt
        behavior = await self._behavior.get(context.tenant)
        if behavior:
            request = self._behavior.apply_to_request(request, behavior)
            context.modified_request = request

        # Compress prompt (skip if NEMOS says compression is hurting)
        if compression_ok:
            compressed = self._compressor.compress(request)
            context.modified_request = compressed
            context.tokens_after = self._compressor.count_tokens(compressed)
        else:
            context.modified_request = request
            context.tokens_after = context.tokens_before

        context.metadata["compression_applied"] = compression_ok

        saved = context.tokens_before - context.tokens_after

        # Formal result (Phase A)
        context.metis_result = MetisResult(
            tokens_before=context.tokens_before,
            tokens_after=context.tokens_after,
            tokens_saved=max(0, saved),
            compression_applied=compression_ok,
            behavior_dial_active=behavior is not None,
            behavior_settings=behavior.model_dump() if behavior else None,
        )

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
            # Update formal result (Phase A)
            if context.metis_result is not None:
                context.metis_result.post_optimization_applied = True

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
