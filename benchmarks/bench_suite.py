"""Benchmark suite runner — load dataset, execute, compute metrics."""

from __future__ import annotations

from pathlib import Path

import yaml

from benchmarks.executors.base import RunResult


def load_dataset(path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data["prompts"]


async def run_executor(executor, prompts: list[dict], name: str = "") -> list[RunResult]:
    results = []
    for row in prompts:
        results.append(await executor.run(row))
    return results


async def compute_all_metrics(
    results: list[RunResult],
    llm_judge_sample_rate: float = 0.0,
) -> dict:
    from benchmarks.metrics.bypass import bypass_stats
    from benchmarks.metrics.cost import cost_stats
    from benchmarks.metrics.decision import decision_stats
    from benchmarks.metrics.latency import latency_stats
    from benchmarks.metrics.quality import quality_stats

    return {
        "cost": cost_stats(results),
        "quality": await quality_stats(results, llm_judge_sample_rate),
        "bypass": bypass_stats(results),
        "latency": latency_stats(results),
        "decision": decision_stats(results),
    }
