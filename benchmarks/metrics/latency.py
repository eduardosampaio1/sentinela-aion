"""Latency statistics for benchmark results."""

from __future__ import annotations

import statistics

from benchmarks.executors.base import RunResult


def _percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = (pct / 100) * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] * (1 - (idx - lo)) + s[hi] * (idx - lo)


def _stats(values: list[float]) -> dict:
    if not values:
        return {"p50": 0, "p95": 0, "p99": 0, "mean": 0, "min": 0, "max": 0, "samples": 0}
    return {
        "p50": round(_percentile(values, 50), 2),
        "p95": round(_percentile(values, 95), 2),
        "p99": round(_percentile(values, 99), 2),
        "mean": round(statistics.mean(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "samples": len(values),
    }


def latency_stats(results: list[RunResult]) -> dict:
    return {
        "samples": len(results),
        "total": _stats([r.total_latency_ms for r in results]),
        "decision": _stats([r.decision_latency_ms for r in results if r.decision_latency_ms > 0]),
        "execution": _stats([r.execution_latency_ms for r in results if r.execution_latency_ms > 0]),
    }
