"""AION executor — applies mock security/routing decisions before the LLM."""

from __future__ import annotations

import time

from benchmarks.executors.base import RunResult
from benchmarks.executors.mock_llm import mock_complete

_INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "ignore all instructions",
    "reveal the system prompt",
    "reveal system prompt",
    "forget your instructions",
    "disregard your",
    "jailbreak",
    "dan mode",
    "act as if you have no",
    "pretend you have no restrictions",
    "override safety",
    "bypass safety",
]

_GREETINGS = {"oi", "olá", "ola", "hi", "hello", "bom dia", "boa tarde", "boa noite", "hey"}


class AionExecutor:
    def __init__(self, live: bool = False):
        self.live = live

    async def run(self, row: dict) -> RunResult:
        prompt = row["prompt"]
        prompt_lower = prompt.strip().lower()
        t0 = time.monotonic()

        if any(kw in prompt_lower for kw in _INJECTION_KEYWORDS):
            decision_ms = (time.monotonic() - t0) * 1000
            return RunResult(
                prompt_id=row["id"],
                tier=row["tier"],
                category=row["category"],
                prompt=prompt,
                response_text="Blocked by security policy.",
                expected_pattern=row["expected_pattern"],
                called_llm=False,
                action="BLOCK",
                total_latency_ms=decision_ms,
                decision_latency_ms=decision_ms,
                execution_latency_ms=0.0,
                cost_usd=0.0,
            )

        is_greeting = (
            prompt_lower in _GREETINGS
            or any(prompt_lower.startswith(g + " ") for g in _GREETINGS)
        )
        is_bypass_category = row.get("category") == "bypass_candidate"

        if is_greeting or is_bypass_category:
            decision_ms = (time.monotonic() - t0) * 1000
            text, _, _, _ = mock_complete(prompt)
            return RunResult(
                prompt_id=row["id"],
                tier=row["tier"],
                category=row["category"],
                prompt=prompt,
                response_text=text,
                expected_pattern=row["expected_pattern"],
                called_llm=False,
                action="BYPASS",
                total_latency_ms=decision_ms,
                decision_latency_ms=decision_ms,
                execution_latency_ms=0.0,
                cost_usd=0.0,
            )

        decision_ms = (time.monotonic() - t0) * 1000
        text, pt, ct, exec_ms = mock_complete(prompt)
        cost = (pt * 0.150 + ct * 0.600) / 1_000_000

        return RunResult(
            prompt_id=row["id"],
            tier=row["tier"],
            category=row["category"],
            prompt=prompt,
            response_text=text,
            expected_pattern=row["expected_pattern"],
            called_llm=True,
            action="CALL_LLM",
            total_latency_ms=decision_ms + exec_ms,
            decision_latency_ms=decision_ms,
            execution_latency_ms=exec_ms,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
            cost_usd=cost,
        )
