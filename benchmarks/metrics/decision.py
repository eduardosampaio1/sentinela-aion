"""Decision action distribution statistics."""

from __future__ import annotations

from collections import Counter

from benchmarks.executors.base import RunResult


def decision_stats(results: list[RunResult]) -> dict:
    total = len(results)
    actions = dict(Counter(r.action for r in results))

    return {
        "total": total,
        "actions": actions,
        "model_distribution": {},
        "confidence": {"mean": 0, "median": 0, "samples": 0},
        "model_by_tier": {},
    }
