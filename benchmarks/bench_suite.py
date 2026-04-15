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

    scenario_name = getattr(args, "scenario", "custom")
    scenario_data = await run_single_scenario(args, scenario=scenario_name, dataset_path=dataset_path)

    output_path = Path(args.output)
    _write_report(scenario_data, args, output_path)

    # Stdout headline
    sv = scenario_data["savings"]
    b_m = scenario_data["baseline"]
    a_m = scenario_data["with_aion"]
    print()
    print("-" * 64)
    print(f"LLM calls:  {b_m['cost']['llm_calls']} -> "
          f"{a_m['cost']['llm_calls']} ({sv['llm_calls_pct_reduction']:+.1f}%)")
    print(f"Tokens:     {b_m['cost']['total_tokens']:,} -> "
          f"{a_m['cost']['total_tokens']:,} ({sv['tokens_pct_reduction']:+.1f}%)")
    print(f"Cost:       ${b_m['cost']['total_cost_usd']:.4f} -> "
          f"${a_m['cost']['total_cost_usd']:.4f} ({sv['cost_pct_reduction']:+.1f}%)")
    b_q = b_m["quality"]["semantic"].get("mean", 0)
    a_q = a_m["quality"]["semantic"].get("mean", 0)
    print(f"Quality:    {b_q:.3f} -> {a_q:.3f}")
    print("-" * 64)
    return 0


_SCENARIO_DATASETS = {
    "conservative": "benchmarks/datasets/bench_suite.yaml",
    "aggressive": "benchmarks/datasets/bench_suite_aggressive.yaml",
}


async def run_single_scenario(args, *, scenario: str, dataset_path: Path) -> dict:
    """Run one scenario end-to-end and return its full metric payload."""
    prompts = load_dataset(dataset_path)

    # Optional sampling (stratified by tier)
    if args.sample and args.sample < len(prompts):
        rng = random.Random(args.seed)
        by_tier: dict[str, list[dict]] = {}
        for p in prompts:
            by_tier.setdefault(p["tier"], []).append(p)
        per_tier_target = max(1, args.sample // max(1, len(by_tier)))
        sampled: list[dict] = []
        for tier_prompts in by_tier.values():
            sampled.extend(rng.sample(tier_prompts, k=min(per_tier_target, len(tier_prompts))))
        prompts = sampled[: args.sample]

    print()
    print("=" * 64)
    print(f"Scenario: {scenario.upper()}  |  prompts: {len(prompts)}  |  "
          f"live: {args.live}  |  llm_judge: {args.llm_judge}")
    print("=" * 64)

    baseline_exec = BaselineExecutor(live=args.live, default_model=args.model)
    aion_exec = AionExecutor(live=args.live, default_model=args.model, tenant=f"bench-{scenario}")

    baseline_results = await run_executor(baseline_exec, prompts, label="Baseline")
    aion_results = await run_executor(aion_exec, prompts, label="With AION")

    baseline_metrics = await compute_all_metrics(
        baseline_results, llm_judge_sample_rate=args.llm_judge,
    )
    aion_metrics = await compute_all_metrics(
        aion_results, llm_judge_sample_rate=args.llm_judge,
    )
    savings = savings_fn(baseline_metrics["cost"], aion_metrics["cost"])

    return {
        "scenario": scenario,
        "dataset": str(dataset_path),
        "n_prompts": len(prompts),
        "baseline": baseline_metrics,
        "with_aion": aion_metrics,
        "savings": savings,
        "baseline_results": baseline_results,
        "aion_results": aion_results,
    }


def _write_report(scenario_data: dict, args, output_path: Path) -> None:
    """Single-scenario report output (markdown + json)."""
    config = {
        "mode": "live" if args.live else "mock",
        "n_prompts": scenario_data["n_prompts"],
        "live": args.live,
        "llm_judge_sample_rate": args.llm_judge,
        "dataset": scenario_data["dataset"],
        "model": args.model,
        "scenario": scenario_data["scenario"],
    }
    markdown = render_markdown(
        baseline=scenario_data["baseline"],
        with_aion=scenario_data["with_aion"],
        savings=scenario_data["savings"],
        config=config,
    )
    output_path.write_text(markdown, encoding="utf-8")
    print(f"[OK] Markdown report: {output_path}")

    json_path = output_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "config": config,
            "baseline": scenario_data["baseline"],
            "with_aion": scenario_data["with_aion"],
            "savings": scenario_data["savings"],
            "baseline_results": [asdict(r) for r in scenario_data["baseline_results"]],
            "aion_results": [asdict(r) for r in scenario_data["aion_results"]],
        }, f, indent=2, default=str)
    print(f"[OK] JSON payload:     {json_path}")


def _write_comparative(scenarios: list[dict], args, output_path: Path) -> None:
    """Comparative report for --scenario both."""
    from benchmarks.report.markdown import render_comparative
    md = render_comparative(scenarios, config={
        "mode": "live" if args.live else "mock",
        "live": args.live,
        "llm_judge_sample_rate": args.llm_judge,
        "model": args.model,
    })
    output_path.write_text(md, encoding="utf-8")
    print(f"[OK] Comparative report: {output_path}")

    json_path = output_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        payload = {
            "config": {
                "mode": "live" if args.live else "mock",
                "live": args.live,
                "llm_judge_sample_rate": args.llm_judge,
                "model": args.model,
            },
            "scenarios": [
                {
                    "scenario": s["scenario"],
                    "n_prompts": s["n_prompts"],
                    "dataset": s["dataset"],
                    "baseline": s["baseline"],
                    "with_aion": s["with_aion"],
                    "savings": s["savings"],
                }
                for s in scenarios
            ],
        }
        json.dump(payload, f, indent=2, default=str)
    print(f"[OK] Comparative JSON:   {json_path}")


async def main_comparative(args: argparse.Namespace) -> int:
    scenarios = []
    for name in ("conservative", "aggressive"):
        dataset_path = Path(_SCENARIO_DATASETS[name])
        if not dataset_path.exists():
            print(f"ERROR: dataset not found: {dataset_path}", file=sys.stderr)
            return 1
        scenarios.append(await run_single_scenario(args, scenario=name, dataset_path=dataset_path))

    # Write individual reports too
    out_base = Path(args.output)
    for s in scenarios:
        ind_path = out_base.with_name(f"{out_base.stem}_{s['scenario']}{out_base.suffix}")
        _write_report(s, args, ind_path)

    _write_comparative(scenarios, args, out_base)

    # Stdout summary
    print()
    print("-" * 64)
    for s in scenarios:
        sv = s["savings"]
        print(f"[{s['scenario']:>12}]  "
              f"LLM -{sv['llm_calls_pct_reduction']:>5.1f}%  |  "
              f"Cost -{sv['cost_pct_reduction']:>5.1f}%  |  "
              f"Tokens -{sv['tokens_pct_reduction']:>5.1f}%  |  "
              f"Quality {s['baseline']['quality']['semantic']['mean']:.3f} -> "
              f"{s['with_aion']['quality']['semantic']['mean']:.3f}")
    print("-" * 64)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AION before-vs-after benchmark")
    parser.add_argument(
        "--scenario", choices=["conservative", "aggressive", "both"],
        default="conservative",
        help=("Dataset scenario. 'conservative' = broad mix (default), "
              "'aggressive' = bypass-heavy + METIS-friendly, "
              "'both' = run both and produce a comparative report."),
    )
    parser.add_argument(
        "--dataset", default=None,
        help="Override dataset path (takes precedence over --scenario)",
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
        if args.scenario == "both":
            return asyncio.run(main_comparative(args))
        # Pick dataset: explicit --dataset wins, else map from scenario
        args.dataset = args.dataset or _SCENARIO_DATASETS.get(args.scenario)
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
