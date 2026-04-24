"""Baseline executor — always calls the LLM, no AION pipeline."""

from __future__ import annotations

from benchmarks.executors.base import RunResult
from benchmarks.executors.mock_llm import mock_complete

_PRICING = {
    "gpt-4o-mini": {"prompt": 0.150, "completion": 0.600},
    "gpt-4o": {"prompt": 5.0, "completion": 15.0},
    "gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
}
_DEFAULT_PRICING = {"prompt": 0.150, "completion": 0.600}


class BaselineExecutor:
    def __init__(self, live: bool = False, default_model: str = "gpt-4o-mini"):
        self.live = live
        self.default_model = default_model

    async def run(self, row: dict) -> RunResult:
        prompt = row["prompt"]
        text, pt, ct, latency = mock_complete(prompt)

        pricing = _PRICING.get(self.default_model, _DEFAULT_PRICING)
        cost = (pt * pricing["prompt"] + ct * pricing["completion"]) / 1_000_000

        return RunResult(
            prompt_id=row["id"],
            tier=row["tier"],
            category=row["category"],
            prompt=prompt,
            response_text=text,
            expected_pattern=row["expected_pattern"],
            called_llm=True,
            action="CALL_LLM",
            total_latency_ms=latency,
            decision_latency_ms=0.0,
            execution_latency_ms=latency,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
            cost_usd=cost,
        )
