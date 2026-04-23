"""Pillar 2 — bypass rate analysis (per tier, per category)."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from benchmarks.executors.base import RunResult


def bypass_stats(results: Iterable[RunResult]) -> dict:
    results = list(results)
    total = len(results)
    if not total:
        return {"total": 0, "bypass_rate": 0.0}

    actions = Counter(r.action for r in results)
    bypassed = actions.get("BYPASS", 0)
    blocked = actions.get("BLOCK", 0)
    llm_called = actions.get("CALL_LLM", 0)
    service_called = actions.get("CALL_SERVICE", 0)

    # Per-tier breakdown
    per_tier: dict[str, dict] = {}
    for r in results:
        tier = r.tier
        if tier not in per_tier:
            per_tier[tier] = {"total": 0, "bypass": 0, "block": 0, "call_llm": 0}
        per_tier[tier]["total"] += 1
        if r.action == "BYPASS":
            per_tier[tier]["bypass"] += 1
        elif r.action == "BLOCK":
            per_tier[tier]["block"] += 1
        elif r.action == "CALL_LLM":
            per_tier[tier]["call_llm"] += 1
    for tier in per_tier:
        t = per_tier[tier]
        t["bypass_rate"] = round(t["bypass"] / t["total"], 3) if t["total"] else 0.0

    # Intent-level breakdown using expected_decision
    expected = Counter()
    for r in results:
        # Parse from prompt row — the executor doesn't carry it, so we infer:
        # Default, we know CALL_LLM means "expected LLM" for tiers medium/complex.
        pass

    return {
        "total": total,
        "bypass": bypassed,
        "bypass_rate": round(bypassed / total, 4),
        "block": blocked,
        "block_rate": round(blocked / total, 4),
        "call_llm": llm_called,
        "call_llm_rate": round(llm_called / total, 4),
        "call_service": service_called,
        "by_tier": per_tier,
    }
