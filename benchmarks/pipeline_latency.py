"""AION Pipeline Latency Benchmark.

Measures p50/p95/p99 of the pre-LLM pipeline (ESTIXE + NOMOS + METIS)
under various concurrency levels.

Usage:
    python -m benchmarks.pipeline_latency
    python -m benchmarks.pipeline_latency --iterations 500 --concurrency 1,10,50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set env before imports
os.environ.setdefault("AION_ESTIXE_ENABLED", "true")
os.environ.setdefault("AION_NOMOS_ENABLED", "true")
os.environ.setdefault("AION_METIS_ENABLED", "true")
os.environ.setdefault("AION_FAIL_MODE", "open")
os.environ.setdefault("OPENAI_API_KEY", "sk-bench-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-bench-key")
os.environ.setdefault("GEMINI_API_KEY", "bench-key")


@dataclass
class BenchResult:
    name: str
    iterations: int
    concurrency: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float
    std_ms: float

    def to_dict(self) -> dict:
        return {k: round(v, 3) if isinstance(v, float) else v for k, v in self.__dict__.items()}


def percentile(data: list[float], p: float) -> float:
    """Calculate percentile value."""
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


def compute_stats(name: str, latencies: list[float], concurrency: int) -> BenchResult:
    return BenchResult(
        name=name,
        iterations=len(latencies),
        concurrency=concurrency,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        mean_ms=statistics.mean(latencies),
        min_ms=min(latencies),
        max_ms=max(latencies),
        std_ms=statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
    )


async def bench_pipeline_pre(n: int, concurrency: int) -> BenchResult:
    """Benchmark the full pre-LLM pipeline."""
    from aion.pipeline import build_pipeline
    from aion.shared.schemas import ChatCompletionRequest, ChatMessage, PipelineContext

    pipeline = build_pipeline()
    # Initialize modules
    for mod in pipeline._pre_modules:
        if hasattr(mod, "initialize"):
            await mod.initialize()

    request = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Explain the concept of recursion in computer science with examples")],
    )

    latencies: list[float] = []

    async def single():
        ctx = PipelineContext(tenant="bench")
        t0 = time.perf_counter_ns()
        await pipeline.run_pre(request, ctx)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
        latencies.append(elapsed_ms)

    sem = asyncio.Semaphore(concurrency)

    async def bounded():
        async with sem:
            await single()

    await asyncio.gather(*[bounded() for _ in range(n)])

    return compute_stats(f"pipeline_pre(c={concurrency})", latencies, concurrency)


async def bench_module_isolated(module_name: str, n: int) -> BenchResult:
    """Benchmark a single module in isolation."""
    from aion.shared.schemas import ChatCompletionRequest, ChatMessage, PipelineContext

    if module_name == "estixe":
        from aion.estixe import get_module
        module = get_module()
    elif module_name == "nomos":
        from aion.nomos import get_module
        module = get_module()
    elif module_name == "metis_pre":
        from aion.metis import get_module
        module = get_module()
    else:
        raise ValueError(f"Unknown module: {module_name}")

    if hasattr(module, "initialize"):
        await module.initialize()

    request = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Explain the concept of recursion in computer science")],
    )

    latencies: list[float] = []

    for _ in range(n):
        ctx = PipelineContext(tenant="bench")
        t0 = time.perf_counter_ns()
        await module.process(request, ctx)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
        latencies.append(elapsed_ms)

    return compute_stats(f"module:{module_name}", latencies, 1)


async def bench_cold_vs_warm(n: int = 100) -> tuple[BenchResult, BenchResult]:
    """Compare first request (cold) vs subsequent (warm)."""
    from aion.pipeline import build_pipeline
    from aion.shared.schemas import ChatCompletionRequest, ChatMessage, PipelineContext

    # Reset singletons to force cold start
    import aion.estixe as estixe_mod
    import aion.nomos as nomos_mod
    estixe_mod._instance = None
    nomos_mod._instance = None

    pipeline = build_pipeline()

    request = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # Cold start (first request triggers initialization)
    ctx = PipelineContext(tenant="bench")
    t0 = time.perf_counter_ns()
    await pipeline.run_pre(request, ctx)
    cold_ms = (time.perf_counter_ns() - t0) / 1e6

    # Warm requests
    warm_latencies: list[float] = []
    for _ in range(n):
        ctx = PipelineContext(tenant="bench")
        t0 = time.perf_counter_ns()
        await pipeline.run_pre(request, ctx)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1e6
        warm_latencies.append(elapsed_ms)

    cold_result = BenchResult(
        name="cold_start", iterations=1, concurrency=1,
        p50_ms=cold_ms, p95_ms=cold_ms, p99_ms=cold_ms,
        mean_ms=cold_ms, min_ms=cold_ms, max_ms=cold_ms, std_ms=0.0,
    )
    warm_result = compute_stats("warm_requests", warm_latencies, 1)
    return cold_result, warm_result


def format_table(results: list[BenchResult]) -> str:
    """Format results as a markdown table."""
    lines = [
        "| Scenario | Iterations | Concurrency | p50 (ms) | p95 (ms) | p99 (ms) | mean (ms) | min (ms) | max (ms) | std (ms) |",
        "|----------|------------|-------------|----------|----------|----------|-----------|----------|----------|----------|",
    ]
    for r in results:
        lines.append(
            f"| {r.name} | {r.iterations} | {r.concurrency} | "
            f"{r.p50_ms:.2f} | {r.p95_ms:.2f} | {r.p99_ms:.2f} | "
            f"{r.mean_ms:.2f} | {r.min_ms:.2f} | {r.max_ms:.2f} | {r.std_ms:.2f} |"
        )
    return "\n".join(lines)


async def run_all(iterations: int, concurrency_levels: list[int]) -> list[BenchResult]:
    """Run all benchmark scenarios."""
    results: list[BenchResult] = []

    print("\n=== AION Pipeline Latency Benchmark ===\n")

    # 1. Module isolation benchmarks
    print("Benchmarking individual modules...")
    for mod in ["estixe", "nomos", "metis_pre"]:
        try:
            r = await bench_module_isolated(mod, iterations)
            results.append(r)
            print(f"  {mod}: p50={r.p50_ms:.2f}ms  p95={r.p95_ms:.2f}ms  p99={r.p99_ms:.2f}ms")
        except Exception as e:
            print(f"  {mod}: SKIPPED ({e})")

    # 2. Full pipeline at various concurrency levels
    print("\nBenchmarking full pipeline (pre-LLM)...")
    for c in concurrency_levels:
        r = await bench_pipeline_pre(iterations, c)
        results.append(r)
        print(f"  concurrency={c}: p50={r.p50_ms:.2f}ms  p95={r.p95_ms:.2f}ms  p99={r.p99_ms:.2f}ms")

    # 3. Cold vs warm
    print("\nBenchmarking cold start vs warm...")
    cold, warm = await bench_cold_vs_warm(iterations)
    results.extend([cold, warm])
    print(f"  cold_start: {cold.mean_ms:.2f}ms")
    print(f"  warm: p50={warm.p50_ms:.2f}ms  p95={warm.p95_ms:.2f}ms  p99={warm.p99_ms:.2f}ms")

    return results


def main():
    parser = argparse.ArgumentParser(description="AION Pipeline Latency Benchmark")
    parser.add_argument("--iterations", "-n", type=int, default=500, help="Iterations per scenario")
    parser.add_argument("--concurrency", "-c", type=str, default="1,10,50", help="Concurrency levels (comma-separated)")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output JSON file")
    args = parser.parse_args()

    concurrency_levels = [int(c) for c in args.concurrency.split(",")]

    results = asyncio.run(run_all(args.iterations, concurrency_levels))

    # Print table
    print("\n" + format_table(results))

    # Save JSON if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump([r.to_dict() for r in results], f, indent=2)
        print(f"\nResults saved to {args.output}")

    print(f"\nTotal scenarios: {len(results)}")


if __name__ == "__main__":
    main()
