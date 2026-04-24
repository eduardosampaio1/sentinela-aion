"""Bypass/block/call-LLM distribution statistics."""

from __future__ import annotations

from collections import defaultdict

from benchmarks.executors.base import RunResult


def bypass_stats(results: list[RunResult]) -> dict:
    total = len(results)
    bypass_count = sum(1 for r in results if r.action == "BYPASS")
    call_llm_count = sum(1 for r in results if r.action == "CALL_LLM")
    block_count = sum(1 for r in results if r.action == "BLOCK")

    by_tier: dict[str, dict] = defaultdict(lambda: {"bypass": 0, "call_llm": 0, "block": 0, "total": 0})
    for r in results:
        by_tier[r.tier]["total"] += 1
        if r.action == "BYPASS":
            by_tier[r.tier]["bypass"] += 1
        elif r.action == "CALL_LLM":
            by_tier[r.tier]["call_llm"] += 1
        elif r.action == "BLOCK":
            by_tier[r.tier]["block"] += 1

    tier_stats = {
        tier: {
            **counts,
            "bypass_rate": round(counts["bypass"] / counts["total"], 4) if counts["total"] else 0.0,
        }
        for tier, counts in by_tier.items()
    }

    return {
        "bypass": bypass_count,
        "call_llm": call_llm_count,
        "block": block_count,
        "total": total,
        "bypass_rate": round(bypass_count / total, 4) if total else 0.0,
        "by_tier": tier_stats,
    }
