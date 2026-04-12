"""Pipeline orchestrator — assembles the module chain based on active config.

Supports:
- SAFE_MODE: bypass all modules, pure passthrough
- Per-component degradation: if a module fails, only that module is disabled
- Health status per module
"""

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


class ModuleStatus:
    """Tracks health status of a single module."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.healthy = True
        self.consecutive_failures = 0
        self.failure_threshold = 3  # degrade after N consecutive failures
        self.last_failure_reason: str = ""

    def record_success(self) -> None:
        self.consecutive_failures = 0
        if not self.healthy:
            self.healthy = True
            logger.info(
                '{"event":"module_recovered","module":"%s"}', self.name,
            )

    def record_failure(self, reason: str) -> None:
        self.consecutive_failures += 1
        self.last_failure_reason = reason
        if self.consecutive_failures >= self.failure_threshold and self.healthy:
            self.healthy = False
            logger.warning(
                '{"event":"module_degraded","module":"%s","failures":%d,"reason":"%s"}',
                self.name, self.consecutive_failures, reason[:100],
            )


class Pipeline:
    """Dynamically assembles and runs the module chain."""

    def __init__(self) -> None:
        self._pre_modules: list[Module] = []
        self._post_modules: list[Module] = []
        self._module_status: dict[str, ModuleStatus] = {}
        self._safe_mode = False
        self._safe_mode_reason: str = ""

    def register_pre(self, module: Module) -> None:
        self._pre_modules.append(module)
        self._module_status[module.name] = ModuleStatus(module.name)
        logger.info("Registered pre-LLM module: %s", module.name)

    def register_post(self, module: Module) -> None:
        self._post_modules.append(module)
        key = f"{module.name}_post"
        self._module_status[key] = ModuleStatus(key)
        logger.info("Registered post-LLM module: %s", module.name)

    @property
    def active_modules(self) -> list[str]:
        return [m.name for m in self._pre_modules + self._post_modules]

    @property
    def is_safe_mode(self) -> bool:
        return self._safe_mode

    def _log_mode_transition(self, from_mode: str, to_mode: str, reason: str, actor: str = "system") -> None:
        """Emit structured mode transition event."""
        logger.warning(
            '{"event":"mode_transition","from":"%s","to":"%s","reason":"%s","actor":"%s"}',
            from_mode, to_mode, reason, actor,
        )

    def activate_safe_mode(self, reason: str = "manual") -> None:
        """Kill switch — disable all modules, pure passthrough."""
        prev_mode = "degraded" if any(not s.healthy for s in self._module_status.values()) else "normal"
        self._safe_mode = True
        self._safe_mode_reason = reason
        self._log_mode_transition(prev_mode, "safe", reason)

    def deactivate_safe_mode(self) -> None:
        """Recover from safe mode."""
        self._safe_mode = False
        self._safe_mode_reason = ""
        self._log_mode_transition("safe", "normal", "manual_recovery")

    def get_health(self) -> dict:
        """Get health status per module."""
        if self._safe_mode:
            return {
                "mode": "safe",
                "safe_mode_reason": self._safe_mode_reason,
                "modules": {
                    name: "bypassed" for name in self._module_status
                },
            }

        module_health = {}
        for name, status in self._module_status.items():
            if status.healthy:
                module_health[name] = "ok"
            else:
                module_health[name] = "degraded"

        degraded = [n for n, s in self._module_status.items() if not s.healthy]
        if degraded:
            mode = "degraded"
        else:
            mode = "normal"

        return {
            "mode": mode,
            "modules": module_health,
            "degraded_components": degraded,
        }

    def get_degraded_headers(self) -> dict[str, str]:
        """Build degradation headers for the response."""
        health = self.get_health()
        headers: dict[str, str] = {}

        if health["mode"] == "safe":
            headers["X-Aion-Degraded"] = "true"
            headers["X-Aion-Degraded-Components"] = "all"
            headers["X-Aion-Degraded-Impact"] = "passthrough"
        elif health["mode"] == "degraded":
            degraded = health.get("degraded_components", [])
            headers["X-Aion-Degraded"] = "true"
            headers["X-Aion-Degraded-Components"] = ",".join(degraded)
            # Map components to impact
            impacts = []
            for comp in degraded:
                if "estixe" in comp:
                    impacts.append("bypass_disabled")
                if "nomos" in comp:
                    impacts.append("routing_fallback")
                if "metis" in comp:
                    impacts.append("optimization_disabled")
            headers["X-Aion-Degraded-Impact"] = ",".join(impacts) if impacts else "partial"

        return headers

    async def run_pre(
        self, request: ChatCompletionRequest, context: PipelineContext
    ) -> PipelineContext:
        """Run pre-LLM modules. May result in bypass or block."""
        context.original_request = request
        context.modified_request = request.model_copy(deep=True)

        # SAFE_MODE: skip everything
        if self._safe_mode:
            context.metadata["safe_mode"] = True
            return context

        settings = get_settings()

        for module in self._pre_modules:
            if context.decision != Decision.CONTINUE:
                break

            # Skip degraded modules (per-component degradation)
            status = self._module_status.get(module.name)
            if status and not status.healthy:
                logger.debug("Skipping degraded module: %s", module.name)
                context.metadata.setdefault("skipped_modules", []).append(module.name)
                continue

            t0 = time.perf_counter()
            try:
                context = await module.process(context.modified_request, context)
                if status:
                    status.record_success()
            except Exception as exc:
                logger.exception("Module %s failed", module.name)
                if status:
                    status.record_failure(str(exc))

                if settings.fail_mode == FailMode.CLOSED:
                    context.set_block(f"Module {module.name} failed (fail-closed)")
                    break
                # fail-open: skip this module, continue to next
                logger.warning("Fail-open: skipping %s, continuing pipeline", module.name)
                context.metadata.setdefault("failed_modules", []).append(module.name)
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
        # SAFE_MODE: skip everything
        if self._safe_mode:
            return response

        settings = get_settings()

        for module in self._post_modules:
            key = f"{module.name}_post"
            status = self._module_status.get(key)

            # Skip degraded post-modules
            if status and not status.healthy:
                logger.debug("Skipping degraded post-module: %s", module.name)
                continue

            t0 = time.perf_counter()
            try:
                context.metadata["llm_response"] = response
                context = await module.process(context.modified_request, context)
                response = context.metadata.get("llm_response", response)
                if status:
                    status.record_success()
            except Exception as exc:
                logger.exception("Post-module %s failed", module.name)
                if status:
                    status.record_failure(str(exc))
                if settings.fail_mode == FailMode.CLOSED:
                    break
                continue
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                context.module_latencies[key] = round(elapsed_ms, 2)

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

        # Calculate cost_saved if NOMOS routed to a different model
        cost_saved = 0.0
        estimated_cost = context.metadata.get("estimated_cost", 0.0)
        if context.selected_model and estimated_cost > 0:
            # cost_saved is the difference vs the default model
            cost_saved = max(0.0, context.metadata.get("default_cost", 0.0) - estimated_cost)

        tokens_saved = max(0, context.tokens_before - context.tokens_after)

        event = TelemetryEvent(
            event_type=decision_str,
            module=module_that_decided,
            request_id=context.request_id,
            decision=decision_str,
            model_used=context.selected_model or "",
            tokens_saved=tokens_saved,
            cost_saved=cost_saved,
            latency_ms=round(total_latency, 2),
            tenant=context.tenant,
            metadata={
                "module_latencies": context.module_latencies,
                "safe_mode": context.metadata.get("safe_mode", False),
                "skipped_modules": context.metadata.get("skipped_modules", []),
                "failed_modules": context.metadata.get("failed_modules", []),
                "complexity_score": context.metadata.get("complexity_score", 0),
                "route_reason": context.metadata.get("route_reason", ""),
            },
        )
        await emit(event)


def build_pipeline() -> Pipeline:
    """Build the pipeline based on current settings."""
    settings = get_settings()
    pipeline = Pipeline()

    # Check if SAFE_MODE is on via env
    if settings.safe_mode:
        pipeline.activate_safe_mode("env_config")
        logger.warning("AION starting in SAFE_MODE — all modules bypassed")
        return pipeline

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
