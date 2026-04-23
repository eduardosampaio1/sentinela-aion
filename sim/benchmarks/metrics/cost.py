"""Pillar 3 — cost and token stats."""

from __future__ import annotations

from typing import Iterable

from benchmarks.executors.base import RunResult


def cost_stats(results: Iterable[RunResult]) -> dict:
    results = list(results)
    total_tokens = sum(r.total_tokens for r in results)
    prompt_tokens = sum(r.prompt_tokens for r in results)
    completion_tokens = sum(r.completion_tokens for r in results)
    cost = sum(r.cost_usd for r in results)
    llm_calls = sum(1 for r in results if r.called_llm)
    total = len(results)

    return {
        "total_requests": total,
        "llm_calls": llm_calls,
        "llm_call_rate": round(llm_calls / total, 4) if total else 0.0,
        "total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_cost_usd": round(cost, 6),
        "cost_per_request_usd": round(cost / total, 6) if total else 0.0,
        "cost_per_llm_call_usd": round(cost / llm_calls, 6) if llm_calls else 0.0,
    }


def savings(baseline: dict, with_aion: dict) -> dict:
    """Compute savings of with_aion vs baseline."""
    def _pct(before: float, after: float) -> float:
        if before <= 0:
            return 0.0
        return round((before - after) / before * 100, 1)

    return {
        "llm_calls_delta": baseline["llm_calls"] - with_aion["llm_calls"],
        "llm_calls_pct_reduction": _pct(baseline["llm_calls"], with_aion["llm_calls"]),
        "tokens_delta": baseline["total_tokens"] - with_aion["total_tokens"],
        "tokens_pct_reduction": _pct(baseline["total_tokens"], with_aion["total_tokens"]),
        "cost_delta_usd": round(baseline["total_cost_usd"] - with_aion["total_cost_usd"], 6),
        "cost_pct_reduction": _pct(baseline["total_cost_usd"], with_aion["total_cost_usd"]),
    }
