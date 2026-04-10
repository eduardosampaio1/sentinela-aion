"""Pipeline orchestrator — assembles the module chain based on active config."""

from __future__ import annotations

import logging
import time
from typing import Protocol, runtime_checkable

from aion.config import FailMode, get_settings
from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Decision,
    PipelineContext,
)
from aion.shared.telemetry import TelemetryEvent, emit

logger = logging.getLogger("aion.pipeline")


@runtime_checkable
class Module(Protocol):
    """Interface that every AION module must implement."""

    name: str

    async def process(
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> PipelineContext:
        """Process the request. May modify context.modified_request or set bypass/block."""
        ...


class Pipeline:
    """Dynamically assembles and runs the module chain."""

    def __init__(self) -> None:
        self._pre_modules: list[Module] = []   # run before LLM call
        self._post_modules: list[Module] = []  # run after LLM response

    def register_pre(self, module: Module) -> None:
        self._pre_modules.append(module)
        logger.info("Registered pre-LLM module: %s", module.name)

    def register_post(self, module: Module) -> None:
        self._post_modules.append(module)
        logger.info("Registered post-LLM module: %s", module.name)

    @property
    def active_modules(self) -> list[str]:
        return [m.name for m in self._pre_modules + self._post_modules]

    async def run_pre(
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> PipelineContext:
        """Run pre-LLM modules. May result in bypass or block."""
        context.original_request = request
        context.modified_request = request.model_copy(deep=True)

        settings = get_settings()

        for module in self._pre_modules:
            if context.decision != Decision.CONTINUE:
                break

            t0 = time.perf_counter()
            try:
                context = await module.process(context.modified_request, context)
            except Exception:
                logger.exception("Module %s failed", module.name)
                if settings.fail_mode == FailMode.CLOSED:
                    context.set_block(f"Module {module.name} failed (fail-closed)")
                    break
                # fail-open: skip this module, continue
                logger.warning("Fail-open: skipping %s", module.name)
                continue
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                context.module_latencies[module.name] = round(elapsed_ms, 2)

        return context

    async def run_post(
        self,
        response: ChatCompletionResponse,
        context: PipelineContext,
    ) -> ChatCompletionResponse:
        """Run post-LLM modules on the response."""
        settings = get_settings()

        for module in self._post_modules:
            t0 = time.perf_counter()
            try:
                # Post modules receive context with original + modified request
                context.metadata["llm_response"] = response
                context = await module.process(context.modified_request, context)
                response = context.metadata.get("llm_response", response)
            except Exception:
                logger.exception("Post-module %s failed", module.name)
                if settings.fail_mode == FailMode.CLOSED:
                    break
                continue
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                context.module_latencies[f"{module.name}_post"] = round(elapsed_ms, 2)

        return response

    async def emit_telemetry(self, context: PipelineContext) -> None:
        """Emit telemetry event for the completed pipeline run."""
        decision_str = context.decision.value
        module_that_decided = "pipeline"

        for module_name, _ in context.module_latencies.items():
            if context.decision != Decision.CONTINUE:
                module_that_decided = module_name.replace("_post", "")
                break

        total_latency = sum(context.module_latencies.values())

        event = TelemetryEvent(
            event_type=decision_str,
            module=module_that_decided,
            request_id=context.request_id,
            decision=decision_str,
            model_used=context.selected_model or "",
            tokens_saved=max(0, context.tokens_before - context.tokens_after),
            latency_ms=round(total_latency, 2),
            tenant=context.tenant,
            metadata={
                "module_latencies": context.module_latencies,
            },
        )
        await emit(event)


def build_pipeline() -> Pipeline:
    """Build the pipeline based on current settings."""
    settings = get_settings()
    pipeline = Pipeline()

    if settings.estixe_enabled:
        from aion.estixe import get_module as get_estixe
        pipeline.register_pre(get_estixe())

    if settings.nomos_enabled:
        from aion.nomos import get_module as get_nomos
        pipeline.register_pre(get_nomos())

    if settings.metis_enabled:
        from aion.metis import get_module as get_metis_pre, get_post_module as get_metis_post
        pipeline.register_pre(get_metis_pre())
        pipeline.register_post(get_metis_post())

    logger.info("Pipeline built with modules: %s", pipeline.active_modules)
    return pipeline
