"""AionExecutor — 'com AION' path.

Runs the full pre-LLM pipeline (ESTIXE + NOMOS + METIS) and builds a
DecisionContract. Based on the contract action:
  - BYPASS / BLOCK / RETURN_RESPONSE: no LLM call, uses adapter response
  - CALL_LLM: executes via mock or live LLM
  - CALL_SERVICE: not covered in the default bench suite
"""

from __future__ import annotations

import time
from typing import Any

from benchmarks.executors.base import RunResult
from benchmarks.executors.baseline import _estimate_cost
from benchmarks.executors.mock_llm import mock_complete


class AionExecutor:
    """'Com AION' — full pipeline + adapter."""

    def __init__(
        self,
        *,
        live: bool = False,
        default_model: str = "gpt-4o-mini",
        tenant: str = "bench",
    ) -> None:
        self.live = live
        self.default_model = default_model
        self.tenant = tenant
        self._pipeline = None

    async def _ensure_pipeline(self):
        if self._pipeline is None:
            from aion.pipeline import build_pipeline
            self._pipeline = build_pipeline()
            # Warm up modules
            for module in self._pipeline._pre_modules:
                if hasattr(module, "initialize"):
                    try:
                        await module.initialize()
                    except Exception:
                        pass

    async def run(self, prompt_row: dict[str, Any]) -> RunResult:
        from aion.config import get_settings
        from aion.contract import Action, build_contract
        from aion.shared.schemas import (
            ChatCompletionRequest,
            ChatMessage,
            Decision,
            PipelineContext,
        )

        prompt = prompt_row.get("prompt", "")
        result = RunResult(
            prompt_id=prompt_row["id"],
            tier=prompt_row["tier"],
            category=prompt_row["category"],
            prompt=prompt,
            response_text="",
            expected_pattern=prompt_row.get("expected_pattern", ""),
        )

        await self._ensure_pipeline()
        settings = get_settings()

        # Build context
        request = ChatCompletionRequest(
            model=self.default_model,
            messages=[ChatMessage(role="user", content=prompt or " ")],
        )
        context = PipelineContext(tenant=self.tenant)
        context.original_request = request
        context.modified_request = request

        # --- Pre-LLM pipeline (AION "brain") ---
        t_pre = time.perf_counter()
        try:
            context = await self._pipeline.run_pre(request, context)
        except Exception as exc:
            result.error = f"pipeline error: {exc}"
            context.decision = Decision.CONTINUE
        result.decision_latency_ms = (time.perf_counter() - t_pre) * 1000

        # --- Build contract ---
        contract = build_contract(
            context,
            active_modules=[m.name for m in self._pipeline._pre_modules],
            operating_mode="stateless",
            decision_latency_ms=result.decision_latency_ms,
            environment=getattr(settings, "environment", "prod"),
        )
        result.action = contract.action.value
        dc = contract.decision_confidence
        result.decision_confidence = dc.score

        # --- Execute per action ---
        if contract.action == Action.BYPASS:
            result.called_llm = False
            result.model_used = "aion-bypass"
            if context.bypass_response and context.bypass_response.choices:
                result.response_text = context.bypass_response.choices[0].message.content or ""
            result.prompt_tokens = 0
            result.completion_tokens = 0
            result.cost_usd = 0.0
            result.execution_latency_ms = 0.0

        elif contract.action == Action.BLOCK:
            result.called_llm = False
            result.model_used = "aion-block"
            result.response_text = context.metadata.get("block_reason", "Request blocked by policy")
            result.prompt_tokens = 0
            result.completion_tokens = 0
            result.cost_usd = 0.0
            result.execution_latency_ms = 0.0

        elif contract.action == Action.CALL_LLM:
            result.called_llm = True
            result.model_used = context.selected_model or self.default_model
            t_exec = time.perf_counter()
            if self.live:
                response_text, pt, ct, _ = await self._live_call(context, request, settings)
            else:
                response_text, pt, ct, _ = mock_complete(prompt)
            result.execution_latency_ms = (time.perf_counter() - t_exec) * 1000
            result.response_text = response_text
            result.prompt_tokens = pt
            result.completion_tokens = ct
            result.cost_usd = _estimate_cost(result.model_used, pt, ct)

        else:
            # CALL_SERVICE / RETURN_RESPONSE / REQUEST_HUMAN_APPROVAL — uncommon in bench suite
            result.called_llm = False
            result.response_text = ""
            result.model_used = contract.action.value
            result.execution_latency_ms = 0.0

        result.total_tokens = result.prompt_tokens + result.completion_tokens
        result.total_latency_ms = result.decision_latency_ms + result.execution_latency_ms
        return result

    async def _live_call(self, context, request, settings) -> tuple[str, int, int, float]:
        from aion.proxy import forward_request
        t0 = time.perf_counter()
        response = await forward_request(request, context, settings)
        latency = (time.perf_counter() - t0) * 1000
        text = response.choices[0].message.content if response.choices else ""
        usage = response.usage
        pt = usage.prompt_tokens if usage else 0
        ct = usage.completion_tokens if usage else 0
        return text, pt, ct, latency
