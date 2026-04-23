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


async def bench_metis_post(n: int) -> BenchResult:
    """METIS post-LLM module in isolation (runs after the LLM call in real flow)."""
    from aion.metis import get_post_module
    from aion.shared.schemas import (
        ChatCompletionChoice,
        ChatCompletionRequest,
        ChatCompletionResponse,
        ChatMessage,
        PipelineContext,
    )

    module = get_post_module()
    request = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Explain recursion briefly.")],
    )
    canned_response = ChatCompletionResponse(
        model="gpt-4o-mini",
        choices=[ChatCompletionChoice(
            index=0,
            message=ChatMessage(role="assistant", content="Recursion is a function that calls itself with a smaller input until a base case is reached."),
        )],
    )

    latencies: list[float] = []
    for _ in range(n):
        ctx = PipelineContext(tenant="bench")
        ctx.metadata["llm_response"] = canned_response
        t0 = time.perf_counter_ns()
        await module.process(request, ctx)
        latencies.append((time.perf_counter_ns() - t0) / 1e6)
    return compute_stats("module:metis_post", latencies, 1)


async def bench_build_contract(n: int) -> BenchResult:
    """Contract builder — consumes a fully-populated PipelineContext."""
    from aion.contract import build_contract
    from aion.shared.schemas import ChatCompletionRequest, ChatMessage, Decision, PipelineContext

    request = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hello")],
    )

    latencies: list[float] = []
    for _ in range(n):
        ctx = PipelineContext(tenant="bench")
        ctx.original_request = request
        ctx.modified_request = request
        ctx.selected_model = "gpt-4o-mini"
        ctx.selected_provider = "openai"
        ctx.decision = Decision.CONTINUE
        ctx.metadata = {
            "complexity_score": 25.0,
            "route_reason": "simple_prompt",
            "estimated_cost": 0.0001,
            "decision_confidence": {"score": 0.72, "factors": ["heuristic", "model_performance"], "maturity": "warm"},
        }
        t0 = time.perf_counter_ns()
        _ = build_contract(
            ctx,
            active_modules=["estixe", "nomos", "metis"],
            operating_mode="learning",
            decision_latency_ms=0.3,
            environment="prod",
        )
        latencies.append((time.perf_counter_ns() - t0) / 1e6)
    return compute_stats("build_contract", latencies, 1)


async def bench_adapter_dispatch(n: int) -> BenchResult:
    """ExecutionAdapter dispatch overhead for a BYPASS action (no LLM call)."""
    from aion.adapter import get_adapter
    from aion.contract import Action, ContractMeta, DecisionContract, FinalOutput
    from aion.shared.schemas import (
        ChatCompletionChoice,
        ChatCompletionResponse,
        ChatMessage,
    )

    response = ChatCompletionResponse(
        model="aion-bypass",
        choices=[ChatCompletionChoice(
            index=0,
            message=ChatMessage(role="assistant", content="Ola!"),
        )],
    )
    contract = DecisionContract(
        request_id="bench_1",
        action=Action.BYPASS,
        final_output=FinalOutput(
            target_type="direct",
            payload={"response": response.model_dump()},
        ),
        meta=ContractMeta(tenant="bench", timestamp=time.time()),
    )

    adapter = get_adapter()
    # Warm up
    await adapter.execute(contract)

    latencies: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        _ = await adapter.execute(contract, stream=False)
        latencies.append((time.perf_counter_ns() - t0) / 1e6)
    return compute_stats("adapter_dispatch(BYPASS)", latencies, 1)


async def bench_end_to_end_endpoints(n: int) -> list[BenchResult]:
    """End-to-end latency per integration mode via the real FastAPI app.

    Uses a TestClient and bypass-triggering payload so no network/LLM is hit.
    Measures the full request-response cycle including middleware, contract
    build, adapter dispatch, and response serialization.
    """
    from fastapi.testclient import TestClient
    from aion.main import app

    client = TestClient(app)
    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "oi"}],
    }

    results: list[BenchResult] = []
    for path, label in [
        ("/v1/chat/completions", "endpoint:transparent"),
        ("/v1/chat/assisted", "endpoint:assisted"),
        ("/v1/decisions", "endpoint:decision"),
    ]:
        # Warm up
        client.post(path, json=body)

        latencies: list[float] = []
        for _ in range(n):
            t0 = time.perf_counter_ns()
            _ = client.post(path, json=body)
            latencies.append((time.perf_counter_ns() - t0) / 1e6)
        results.append(compute_stats(label, latencies, 1))
    return results


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

    # 2. METIS post-LLM (runs after the LLM call in the real flow)
    try:
        r = await bench_metis_post(iterations)
        results.append(r)
        print(f"  metis_post: p50={r.p50_ms:.2f}ms  p95={r.p95_ms:.2f}ms  p99={r.p99_ms:.2f}ms")
    except Exception as e:
        print(f"  metis_post: SKIPPED ({e})")

    # 3. Contract layer (new: build_contract + adapter dispatch)
    print("\nBenchmarking contract layer...")
    try:
        r = await bench_build_contract(iterations)
        results.append(r)
        print(f"  build_contract: p50={r.p50_ms:.2f}ms  p95={r.p95_ms:.2f}ms  p99={r.p99_ms:.2f}ms")
    except Exception as e:
        print(f"  build_contract: SKIPPED ({e})")
    try:
        r = await bench_adapter_dispatch(iterations)
        results.append(r)
        print(f"  adapter_dispatch: p50={r.p50_ms:.2f}ms  p95={r.p95_ms:.2f}ms  p99={r.p99_ms:.2f}ms")
    except Exception as e:
        print(f"  adapter_dispatch: SKIPPED ({e})")

    # 4. Full pipeline at various concurrency levels
    print("\nBenchmarking full pipeline (pre-LLM)...")
    for c in concurrency_levels:
        r = await bench_pipeline_pre(iterations, c)
        results.append(r)
        print(f"  concurrency={c}: p50={r.p50_ms:.2f}ms  p95={r.p95_ms:.2f}ms  p99={r.p99_ms:.2f}ms")

    # 5. End-to-end per integration mode (real HTTP stack, minus LLM)
    print("\nBenchmarking end-to-end endpoints (bypass-triggering payload)...")
    try:
        # smaller iteration count for HTTP roundtrip (heavier)
        endpoint_iters = max(50, iterations // 4)
        ep_results = await bench_end_to_end_endpoints(endpoint_iters)
        results.extend(ep_results)
        for r in ep_results:
            print(f"  {r.name}: p50={r.p50_ms:.2f}ms  p95={r.p95_ms:.2f}ms  p99={r.p99_ms:.2f}ms")
    except Exception as e:
        print(f"  endpoints: SKIPPED ({e})")

    # 6. Cold vs warm
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
