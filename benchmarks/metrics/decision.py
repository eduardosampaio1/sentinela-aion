"""Pillar 5 — decision intelligence stats (model distribution, confidence)."""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Iterable

from benchmarks.executors.base import RunResult


def decision_stats(results: Iterable[RunResult]) -> dict:
    results = list(results)
    total = len(results)
    if not total:
        return {"total": 0}

    actions = Counter(r.action for r in results)
    models = Counter(r.model_used for r in results if r.model_used)
    confidences = [r.decision_confidence for r in results if r.decision_confidence > 0]

    per_tier_models: dict[str, Counter] = {}
    for r in results:
        per_tier_models.setdefault(r.tier, Counter())
        per_tier_models[r.tier][r.model_used or "unknown"] += 1

    return {
        "total": total,
        "actions": dict(actions),
        "model_distribution": dict(models),
        "confidence": {
            "mean": round(statistics.mean(confidences), 3) if confidences else 0.0,
            "median": round(statistics.median(confidences), 3) if confidences else 0.0,
            "samples": len(confidences),
        },
        "model_by_tier": {
            tier: dict(counter) for tier, counter in per_tier_models.items()
        },
    }
