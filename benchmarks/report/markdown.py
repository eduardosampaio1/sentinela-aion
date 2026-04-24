"""Markdown report renderers for benchmark results."""

from __future__ import annotations


def render_markdown(
    baseline: dict,
    with_aion: dict,
    savings: dict,
    config: dict,
) -> str:
    n = config.get("n_prompts", "?")
    mode = config.get("mode", "mock")
    live = config.get("live", False)

    b_cost = baseline.get("cost", {})
    a_cost = with_aion.get("cost", {})
    b_lat = baseline.get("latency", {})
    a_lat = with_aion.get("latency", {})
    b_qual = baseline.get("quality", {})
    a_qual = with_aion.get("quality", {})
    a_bypass = with_aion.get("bypass", {})

    lines = [
        "# AION Benchmark",
        "",
        f"**Mode:** {mode} | **Prompts:** {n} | **Live:** {live}",
        "",
        "## Chamadas LLM",
        "",
        "| Metric | Baseline | With AION | Savings |",
        "|--------|----------|-----------|---------|",
        (
            f"| LLM calls | {b_cost.get('llm_calls', 0)} | {a_cost.get('llm_calls', 0)}"
            f" | {savings.get('llm_calls_delta', 0)} (-{savings.get('llm_calls_pct_reduction', 0):.1f}%) |"
        ),
        (
            f"| Total tokens | {b_cost.get('total_tokens', 0)} | {a_cost.get('total_tokens', 0)}"
            f" | -{savings.get('tokens_pct_reduction', 0):.1f}% |"
        ),
        (
            f"| Cost USD | ${b_cost.get('total_cost_usd', 0):.6f} | ${a_cost.get('total_cost_usd', 0):.6f}"
            f" | -{savings.get('cost_pct_reduction', 0):.1f}% |"
        ),
        "",
        "## Bypass rate",
        "",
        f"Bypass rate: {a_bypass.get('bypass_rate', 0):.2%}",
        "",
        "## Latência",
        "",
        "| Metric | Baseline p50 | With AION p50 |",
        "|--------|-------------|---------------|",
        (
            f"| Total | {b_lat.get('total', {}).get('p50', 0)} ms"
            f" | {a_lat.get('total', {}).get('p50', 0)} ms |"
        ),
        "",
        "## Qualidade",
        "",
        "| Metric | Baseline | With AION |",
        "|--------|----------|-----------|",
        (
            f"| Semantic mean | {b_qual.get('semantic', {}).get('mean', 0):.4f}"
            f" | {a_qual.get('semantic', {}).get('mean', 0):.4f} |"
        ),
        "",
    ]
    return "\n".join(lines)


def render_comparative(scenarios: list[dict], config: dict) -> str:
    lines = [
        "# AION Comparative Benchmark",
        "",
        "## Comparative",
        "",
        "| Scenario | Bypass Rate | Cost Reduction | Token Reduction |",
        "|----------|-------------|----------------|-----------------|",
    ]

    for s in scenarios:
        name = s["scenario"].title()
        sv = s.get("savings", {})
        bypass_pct = sv.get("llm_calls_pct_reduction", 0)
        cost_pct = sv.get("cost_pct_reduction", 0)
        tokens_pct = sv.get("tokens_pct_reduction", 0)
        lines.append(f"| {name} | {bypass_pct:.1f}% | {cost_pct:.1f}% | {tokens_pct:.1f}% |")

    lines.append("")

    if len(scenarios) >= 2:
        first = scenarios[0].get("savings", {})
        last = scenarios[-1].get("savings", {})
        delta_bypass = last.get("llm_calls_pct_reduction", 0) - first.get("llm_calls_pct_reduction", 0)
        delta_cost = last.get("cost_pct_reduction", 0) - first.get("cost_pct_reduction", 0)

        sign_b = "+" if delta_bypass >= 0 else ""
        sign_c = "+" if delta_cost >= 0 else ""

        lines += [
            "## Delta entre cenarios",
            "",
            f"Bypass delta: {sign_b}{delta_bypass:.1f} p.p.",
            f"Cost delta: {sign_c}{delta_cost:.1f} p.p.",
            "",
        ]

    return "\n".join(lines)
