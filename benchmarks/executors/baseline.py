"""BaselineExecutor — 'no AION' path.

Every prompt hits the LLM directly. In mock mode uses ``mock_complete``;
in live mode uses the real LLM via aion.proxy (reusing the existing
circuit-breaker and retry logic for fairness).
"""

from __future__ import annotations

import time
from typing import Any

from benchmarks.executors.base import RunResult
from benchmarks.executors.mock_llm import mock_complete


class BaselineExecutor:
    """'Sem AION' — direct LLM call, no pipeline."""

    def __init__(self, *, live: bool = False, default_model: str = "gpt-4o-mini") -> None:
        self.live = live
        self.default_model = default_model

    async def run(self, prompt_row: dict[str, Any]) -> RunResult:
        prompt = prompt_row.get("prompt", "")
        result = RunResult(
            prompt_id=prompt_row["id"],
            tier=prompt_row["tier"],
            category=prompt_row["category"],
            prompt=prompt,
            response_text="",
            expected_pattern=prompt_row.get("expected_pattern", ""),
            called_llm=True,
            action="CALL_LLM",
            model_used=self.default_model,
        )

        t0 = time.perf_counter()
        if self.live:
            response_text, pt, ct, _ = await self._live_call(prompt)
        else:
            response_text, pt, ct, _ = mock_complete(prompt)
        result.execution_latency_ms = (time.perf_counter() - t0) * 1000
        result.total_latency_ms = result.execution_latency_ms
        result.response_text = response_text
        result.prompt_tokens = pt
        result.completion_tokens = ct
        result.total_tokens = pt + ct
        result.cost_usd = _estimate_cost(self.default_model, pt, ct)
        return result

    async def _live_call(self, prompt: str) -> tuple[str, int, int, float]:
        from aion.config import get_settings
        from aion.proxy import forward_request
        from aion.shared.schemas import (
            ChatCompletionRequest,
            ChatMessage,
            PipelineContext,
        )

        settings = get_settings()
        request = ChatCompletionRequest(
            model=self.default_model,
            messages=[ChatMessage(role="user", content=prompt)],
        )
        ctx = PipelineContext(
            tenant="bench",
            selected_model=self.default_model,
            selected_provider="openai",
        )
        t0 = time.perf_counter()
        response = await forward_request(request, ctx, settings)
        latency = (time.perf_counter() - t0) * 1000
        text = response.choices[0].message.content if response.choices else ""
        usage = response.usage
        pt = usage.prompt_tokens if usage else 0
        ct = usage.completion_tokens if usage else 0
        return text, pt, ct, latency


# Static pricing table (USD per 1k tokens) — keeps cost estimate free of async IO.
# Source: config/models.yaml snapshot. Update if prices change.
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "claude-sonnet-4-6": (0.003, 0.015),
    "gemini-2.0-flash": (0.0001, 0.0004),
    "aion-bypass": (0.0, 0.0),
    "aion-block": (0.0, 0.0),
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Synchronous cost estimate using static pricing table.

    The table mirrors ``config/models.yaml``. Unknown models fall back to
    gpt-4o-mini pricing (cheapest tier) so we never overestimate baseline savings.
    """
    input_rate, output_rate = _PRICING.get(model, _PRICING["gpt-4o-mini"])
    return round((prompt_tokens / 1000) * input_rate + (completion_tokens / 1000) * output_rate, 8)
