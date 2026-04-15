"""Pillar 1 — latency stats (p50/p95/p99 on total, execution, decision)."""

from __future__ import annotations

import statistics
from typing import Iterable

from benchmarks.executors.base import RunResult


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = int(len(s) * p / 100)
    return s[min(idx, len(s) - 1)]


def latency_stats(results: Iterable[RunResult]) -> dict:
    results = list(results)
    totals = [r.total_latency_ms for r in results]
    decisions = [r.decision_latency_ms for r in results if r.decision_latency_ms > 0]
    executions = [r.execution_latency_ms for r in results if r.execution_latency_ms > 0]

    def _summary(values: list[float]) -> dict:
        if not values:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0, "samples": 0}
        return {
            "p50": round(_percentile(values, 50), 2),
            "p95": round(_percentile(values, 95), 2),
            "p99": round(_percentile(values, 99), 2),
            "mean": round(statistics.mean(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "samples": len(values),
        }

    return {
        "total": _summary(totals),
        "decision": _summary(decisions),
        "execution": _summary(executions),
        "samples": len(results),
    }
