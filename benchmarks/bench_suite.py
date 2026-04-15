"""AION before-vs-after benchmark suite — 5 pillars.

Runs the same dataset through Baseline (no AION) and With AION executors,
produces a markdown + JSON report comparing latency, bypass rate, cost,
quality, and decision intelligence.

Usage:
    python -m benchmarks.bench_suite
    python -m benchmarks.bench_suite --sample 30 --output report.md
    python -m benchmarks.bench_suite --live --llm-judge 0.1
    python -m benchmarks.bench_suite --dataset benchmarks/datasets/bench_suite.yaml

Exit codes:
    0 — success
    1 — any error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Sensible defaults for env (can be overridden before import)
os.environ.setdefault("AION_ESTIXE_ENABLED", "true")
os.environ.setdefault("AION_NOMOS_ENABLED", "true")
os.environ.setdefault("AION_METIS_ENABLED", "true")
os.environ.setdefault("AION_FAIL_MODE", "open")
os.environ.setdefault("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "sk-bench-key"))
os.environ.setdefault("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "sk-bench-key"))
os.environ.setdefault("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", "bench-key"))

from benchmarks.executors import AionExecutor, BaselineExecutor
from benchmarks.metrics import (
    bypass_stats,
    cost_stats,
    decision_stats,
    latency_stats,
    quality_stats,
)
from benchmarks.metrics.cost import savings as savings_fn
from benchmarks.report import render_markdown

logger = logging.getLogger("benchmarks.bench_suite")


def load_dataset(path: Path) -> list[dict]:
    """Load prompts from YAML. Returns list of prompt dicts."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("prompts", [])


async def run_executor(executor, prompts: list[dict], label: str) -> list:
    """Run every prompt through the executor, collecting RunResults."""
    print(f"\n>> Running {label} ({len(prompts)} prompts)...")
    results = []
    for i, prompt in enumerate(prompts):
        try:
            result = await executor.run(prompt)
            results.append(result)
        except Exception as exc:
            logger.exception("prompt %s failed", prompt.get("id"))
            # Create error placeholder to keep counts consistent
            from benchmarks.executors.base import RunResult
            results.append(RunResult(
                prompt_id=prompt.get("id", f"unknown_{i}"),
                tier=prompt.get("tier", "unknown"),
                category=prompt.get("category", "unknown"),
                prompt=prompt.get("prompt", ""),
                response_text="",
                expected_pattern=prompt.get("expected_pattern", ""),
                error=str(exc),
            ))
        if (i + 1) % 20 == 0 or (i + 1) == len(prompts):
            print(f"  {label}: {i + 1}/{len(prompts)}")
    return results


async def compute_all_metrics(results: list, *, llm_judge_sample_rate: float) -> dict:
    """Aggregate all pillar metrics for a run."""
    return {
        "latency": latency_stats(results),
        "cost": cost_stats(results),
        "bypass": bypass_stats(results),
        "decision": decision_stats(results),
        "quality": await quality_stats(
            results, llm_judge_sample_rate=llm_judge_sample_rate,
        ),
    }


async def main_async(args: argparse.Namespace) -> int:
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"ERROR: dataset not found: {dataset_path}", file=sys.stderr)
        return 1

    prompts = load_dataset(dataset_path)

    # Optional sampling
    if args.sample and args.sample < len(prompts):
        rng = random.Random(args.seed)
        # Stratified sample across tiers so comparisons stay meaningful
        by_tier: dict[str, list[dict]] = {}
        for p in prompts:
            by_tier.setdefault(p["tier"], []).append(p)
        per_tier_target = max(1, args.sample // max(1, len(by_tier)))
        sampled: list[dict] = []
        for tier_prompts in by_tier.values():
            sampled.extend(rng.sample(tier_prompts, k=min(per_tier_target, len(tier_prompts))))
        prompts = sampled[: args.sample]

    print("=" * 64)
    print(f"AION Benchmark — {len(prompts)} prompts, "
          f"live={args.live}, llm_judge={args.llm_judge}")
    print("=" * 64)

    baseline_exec = BaselineExecutor(live=args.live, default_model=args.model)
    aion_exec = AionExecutor(live=args.live, default_model=args.model, tenant="bench")

    # Run both
    baseline_results = await run_executor(baseline_exec, prompts, label="Baseline")
    aion_results = await run_executor(aion_exec, prompts, label="With AION")

    # Compute metrics
    baseline_metrics = await compute_all_metrics(
        baseline_results, llm_judge_sample_rate=args.llm_judge,
    )
    aion_metrics = await compute_all_metrics(
        aion_results, llm_judge_sample_rate=args.llm_judge,
    )
    savings = savings_fn(baseline_metrics["cost"], aion_metrics["cost"])

    config = {
        "mode": "live" if args.live else "mock",
        "n_prompts": len(prompts),
        "live": args.live,
        "llm_judge_sample_rate": args.llm_judge,
        "dataset": str(dataset_path),
        "model": args.model,
    }

    # Render reports
    markdown = render_markdown(
        baseline=baseline_metrics,
        with_aion=aion_metrics,
        savings=savings,
        config=config,
    )
    output_path = Path(args.output)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"\n[OK] Markdown report: {output_path}")

    # JSON dump for programmatic consumption
    json_path = output_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "config": config,
            "baseline": baseline_metrics,
            "with_aion": aion_metrics,
            "savings": savings,
            "baseline_results": [asdict(r) for r in baseline_results],
            "aion_results": [asdict(r) for r in aion_results],
        }, f, indent=2, default=str)
    print(f"[OK] JSON payload:     {json_path}")

    # Print headline to stdout
    print()
    print("-" * 64)
    print(f"LLM calls:  {baseline_metrics['cost']['llm_calls']} -> "
          f"{aion_metrics['cost']['llm_calls']} ({savings['llm_calls_pct_reduction']:+.1f}%)")
    print(f"Tokens:     {baseline_metrics['cost']['total_tokens']:,} -> "
          f"{aion_metrics['cost']['total_tokens']:,} ({savings['tokens_pct_reduction']:+.1f}%)")
    print(f"Cost:       ${baseline_metrics['cost']['total_cost_usd']:.4f} -> "
          f"${aion_metrics['cost']['total_cost_usd']:.4f} ({savings['cost_pct_reduction']:+.1f}%)")
    b_q = baseline_metrics["quality"]["semantic"].get("mean", 0)
    a_q = aion_metrics["quality"]["semantic"].get("mean", 0)
    print(f"Quality:    {b_q:.3f} -> {a_q:.3f}")
    print("-" * 64)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AION before-vs-after benchmark")
    parser.add_argument(
        "--dataset", default="benchmarks/datasets/bench_suite.yaml",
        help="Path to bench dataset YAML",
    )
    parser.add_argument("--sample", type=int, default=0,
                        help="If >0, randomly sample N prompts (stratified by tier)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    parser.add_argument("--output", default="bench_report.md",
                        help="Markdown report output path")
    parser.add_argument("--live", action="store_true",
                        help="Use real LLM (default: deterministic mock)")
    parser.add_argument("--llm-judge", type=float, default=0.0,
                        help="LLM-as-judge sample rate (0.0-1.0, default 0 = off)")
    parser.add_argument("--model", default="gpt-4o-mini",
                        help="Default model name (baseline uses it; AION may route elsewhere)")
    args = parser.parse_args()

    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
