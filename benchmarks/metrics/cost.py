"""Cost statistics and savings computation for benchmark results."""

from __future__ import annotations

from benchmarks.executors.base import RunResult


def cost_stats(results: list[RunResult]) -> dict:
    total = len(results)
    llm_calls = sum(1 for r in results if r.called_llm)
    total_tokens = sum(r.total_tokens for r in results)
    prompt_tokens = sum(r.prompt_tokens for r in results)
    completion_tokens = sum(r.completion_tokens for r in results)
    total_cost = sum(r.cost_usd for r in results)

    return {
        "total_requests": total,
        "llm_calls": llm_calls,
        "llm_call_rate": round(llm_calls / total, 4) if total else 0.0,
        "total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_cost_usd": round(total_cost, 6),
    }


def savings(baseline: dict, with_aion: dict) -> dict:
    b_calls = baseline["llm_calls"]
    a_calls = with_aion["llm_calls"]
    calls_delta = b_calls - a_calls
    calls_pct = round(calls_delta / b_calls * 100, 4) if b_calls else 0.0

    b_tokens = baseline["total_tokens"]
    a_tokens = with_aion["total_tokens"]
    tokens_delta = b_tokens - a_tokens
    tokens_pct = round(tokens_delta / b_tokens * 100, 4) if b_tokens else 0.0

    b_cost = baseline["total_cost_usd"]
    a_cost = with_aion["total_cost_usd"]
    cost_delta = round(b_cost - a_cost, 6)
    cost_pct = round(cost_delta / b_cost * 100, 4) if b_cost else 0.0

    return {
        "llm_calls_delta": calls_delta,
        "llm_calls_pct_reduction": calls_pct,
        "tokens_delta": tokens_delta,
        "tokens_pct_reduction": tokens_pct,
        "cost_delta_usd": cost_delta,
        "cost_pct_reduction": cost_pct,
    }
