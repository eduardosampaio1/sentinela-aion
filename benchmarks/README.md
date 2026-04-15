# AION Benchmarks

Tools to measure AION's operational value against a baseline (vanilla LLM gateway).

## Benchmarks

| Script | Purpose |
|--------|---------|
| `pipeline_latency.py` | Micro-benchmark: p50/p95/p99 of the AION pipeline alone |
| `bench_suite.py` | **Macro-benchmark**: before vs after AION across 5 pillars |

## Before-vs-After Benchmark (`bench_suite.py`)

The 5 pillars:

1. **Latency** — decision_latency_ms (AION), execution_latency_ms (LLM/service), total
2. **Bypass rate** — % of requests resolved without LLM
3. **Cost** — tokens, LLM calls, USD
4. **Quality** — semantic similarity + optional LLM-as-judge
5. **Decision intelligence** — model distribution, confidence

### Quick start (mock, fast, free)

```bash
# Full 133-prompt suite with deterministic mock
python -m benchmarks.bench_suite --output bench_report.md

# Small sample for smoke test
python -m benchmarks.bench_suite --sample 30 --output smoke.md
```

### Live (real LLM — costs $)

```bash
export OPENAI_API_KEY=sk-...
python -m benchmarks.bench_suite --live --sample 50 --output live_report.md
```

### Full evaluation with LLM-as-judge

```bash
python -m benchmarks.bench_suite --live --llm-judge 0.1 --output eval_report.md
```

This runs semantic similarity on all prompts and LLM-as-judge on a 10% sample
for cross-validation. Requires a valid OpenAI key (uses gpt-4o-mini as the judge).

## Output

Two artifacts per run:

- `bench_report.md` — human-readable report with pillar summary, tables, TL;DR
- `bench_report.json` — raw metrics + full per-prompt results for programmatic use

## Dataset

`datasets/bench_suite.yaml` — 133 curated prompts:

- **Simple (49)**: bypass candidates (greetings, thanks, farewells) + factual short-form
- **Medium (48)**: routing decisions (code, analysis, howto)
- **Complex (26)**: hard routing (system design, algorithms, strategy)
- **Edge (10)**: edge cases (empty, injection, PII, ambiguous, emoji)

Each prompt has `expected_pattern` used for semantic similarity. Versioned with
`version: "1.0"` at the top of the YAML.

## Architecture

```
benchmarks/
├── bench_suite.py          # orchestrator (CLI)
├── datasets/
│   └── bench_suite.yaml    # 133 prompts
├── executors/
│   ├── base.py             # RunResult dataclass
│   ├── mock_llm.py         # deterministic mock (default)
│   ├── baseline.py         # direct LLM call
│   └── with_aion.py        # full pipeline + adapter
├── metrics/
│   ├── latency.py          # pillar 1
│   ├── bypass.py           # pillar 2
│   ├── cost.py             # pillar 3
│   ├── quality.py          # pillar 4 (semantic + LLM-judge)
│   └── decision.py         # pillar 5
└── report/
    └── markdown.py         # markdown rendering
```

## Interpreting results

A healthy "AION wins" run looks like:

- LLM calls reduced ≥ 15%
- Cost reduced ≥ 15%
- Quality delta within ±5% (semantic similarity is noisy)
- Decision confidence > 0.60

If quality drops significantly, check:

1. Is the dataset mix appropriate? (too many bypass_candidates inflates bypass rate)
2. Are bypass templates too generic for your use case?
3. Does NOMOS have enough models configured in `config/models.yaml`?

## CI usage

The mock mode is deterministic and cheap — safe to run in CI:

```bash
python -m benchmarks.bench_suite --sample 50 --output ci_bench.md
```

Parse the JSON to enforce regression thresholds:

```bash
python -c "
import json
d = json.load(open('ci_bench.json'))
assert d['savings']['cost_pct_reduction'] > 10, 'regression: cost savings below 10%'
"
```
