"""Markdown report rendering for the 5-pillar benchmark.

The report shows **before (Baseline) vs after (AION)** across every pillar,
with concrete deltas so the value is immediately visible.
"""

from __future__ import annotations


def _pct(value: float, suffix: str = "%") -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}{suffix}"


def _fmt_num(n) -> str:
    if isinstance(n, float):
        return f"{n:.2f}"
    return str(n)


def render_comparative(scenarios: list[dict], config: dict) -> str:
    """Comparative report across multiple scenarios (e.g. conservative vs aggressive).

    Each element of ``scenarios`` is the dict returned by
    ``bench_suite.run_single_scenario`` — contains baseline, with_aion, savings.
    """
    lines: list[str] = []
    lines.append("# AION Benchmark — Comparative (conservative vs aggressive)")
    lines.append("")
    lines.append(
        f"**Config**: mode=`{config['mode']}`, live={config['live']}, "
        f"llm_judge={config['llm_judge_sample_rate']}, model={config['model']}"
    )
    lines.append("")
    lines.append(
        "> **Por que dois cenarios?**  O cenario *conservative* tem distribuicao realista "
        "ampla (mix simples/medio/complexo) e mede o caso 'sem piorar'. O cenario "
        "*aggressive* tem distribuicao tipica de atendimento (muitas saudacoes, acks, "
        "inputs grandes) onde o AION brilha economicamente. Juntos mostram:"
    )
    lines.append("")
    lines.append(
        "1. **Cenario conservador**: AION nao prejudica nada, mesmo em traffic generico")
    lines.append(
        "2. **Cenario agressivo**: AION converte trafego real em economia expressiva")
    lines.append("")

    # Side-by-side comparison table
    lines.append("## Comparativo lado a lado")
    lines.append("")
    header = "| Métrica |"
    sep = "|---|"
    for s in scenarios:
        header += f" {s['scenario'].title()} |"
        sep += "---|"
    lines.append(header)
    lines.append(sep)

    def _cell(value: float, fmt: str = "{:.1f}%") -> str:
        return fmt.format(value)

    # LLM call reduction
    row = "| **LLM calls reduzidas** |"
    for s in scenarios:
        row += f" {_cell(s['savings']['llm_calls_pct_reduction'])} |"
    lines.append(row)

    # Cost reduction
    row = "| **Custo reduzido** |"
    for s in scenarios:
        row += f" {_cell(s['savings']['cost_pct_reduction'])} |"
    lines.append(row)

    # Tokens reduction
    row = "| Tokens reduzidos |"
    for s in scenarios:
        row += f" {_cell(s['savings']['tokens_pct_reduction'])} |"
    lines.append(row)

    # Bypass rate
    row = "| Bypass rate (AION) |"
    for s in scenarios:
        row += f" {s['with_aion']['bypass']['bypass_rate'] * 100:.1f}% |"
    lines.append(row)

    # Quality delta
    row = "| Qualidade (delta) |"
    for s in scenarios:
        b_q = s["baseline"]["quality"]["semantic"].get("mean", 0)
        a_q = s["with_aion"]["quality"]["semantic"].get("mean", 0)
        delta = ((a_q - b_q) / b_q * 100) if b_q else 0
        row += f" {_pct(delta)} ({b_q:.2f} → {a_q:.2f}) |"
    lines.append(row)

    # Decision latency added
    row = "| Decision latency p95 |"
    for s in scenarios:
        p95 = s["with_aion"]["latency"]["decision"].get("p95", 0)
        row += f" {p95:.2f} ms |"
    lines.append(row)

    # Prompt counts
    row = "| Prompts no dataset |"
    for s in scenarios:
        row += f" {s['n_prompts']} |"
    lines.append(row)

    lines.append("")

    # Headline interpretation
    agg = next((s for s in scenarios if s["scenario"] == "aggressive"), None)
    cons = next((s for s in scenarios if s["scenario"] == "conservative"), None)
    if agg and cons:
        lines.append("## Leitura do resultado")
        lines.append("")
        lines.append(
            f"- **Conservative**: {cons['savings']['llm_calls_pct_reduction']:.1f}% "
            f"menos chamadas LLM, {cons['savings']['cost_pct_reduction']:.1f}% menos custo "
            f"— prova que AION nao degrada operacao generica."
        )
        lines.append(
            f"- **Aggressive**: {agg['savings']['llm_calls_pct_reduction']:.1f}% "
            f"menos chamadas LLM, {agg['savings']['cost_pct_reduction']:.1f}% menos custo "
            f"— ganho real em traffic tipico de atendimento/chat."
        )
        lines.append("")
        delta_llm = agg["savings"]["llm_calls_pct_reduction"] - cons["savings"]["llm_calls_pct_reduction"]
        lines.append(
            f"> **Delta entre cenarios**: o salto de +{delta_llm:.1f}p.p. em LLM calls "
            "reduzidas entre conservative e aggressive mostra que o valor do AION escala "
            "com quanto de traffic e *bypass-able* — caracteristica tipica de chat/support."
        )
        lines.append("")

    # Per-scenario summary links
    lines.append("## Detalhamento por cenario")
    lines.append("")
    for s in scenarios:
        lines.append(f"### {s['scenario'].title()}")
        lines.append("")
        lines.append(f"- Prompts: {s['n_prompts']}")
        lines.append(f"- Dataset: `{s['dataset']}`")
        lines.append(
            f"- Baseline: {s['baseline']['cost']['llm_calls']} LLM calls, "
            f"${s['baseline']['cost']['total_cost_usd']:.4f} total"
        )
        lines.append(
            f"- With AION: {s['with_aion']['cost']['llm_calls']} LLM calls, "
            f"${s['with_aion']['cost']['total_cost_usd']:.4f} total"
        )
        # Decision mix
        actions = s["with_aion"]["decision"]["actions"]
        action_str = ", ".join(f"{k}={v}" for k, v in sorted(actions.items(), key=lambda x: -x[1]))
        lines.append(f"- Decisoes AION: {action_str}")
        lines.append("")

    return "\n".join(lines)


def render_markdown(
    *,
    baseline: dict,
    with_aion: dict,
    savings: dict,
    config: dict,
) -> str:
    lines: list[str] = []

    lines.append("# AION Benchmark — Before vs After")
    lines.append("")
    lines.append(
        f"**Config**: mode=`{config['mode']}`, prompts={config['n_prompts']}, "
        f"live={config['live']}, llm_judge_sample={config['llm_judge_sample_rate']}"
    )
    lines.append("")
    lines.append(
        "> **TL;DR**: AION decides, NOMOS routes, METIS optimizes. The table below shows "
        "what that buys you vs a vanilla LLM gateway."
    )
    lines.append("")

    # ── Pillar summary table ──
    lines.append("## Pillars — Summary")
    lines.append("")
    lines.append("| Métrica | Sem AION (baseline) | Com AION | Delta |")
    lines.append("|---|---|---|---|")

    # 1. Latência
    b_lat = baseline["latency"]["total"]
    a_lat = with_aion["latency"]["total"]
    lines.append(
        f"| Latência média (mean) | {b_lat['mean']:.1f} ms | {a_lat['mean']:.1f} ms | "
        f"{_pct(((b_lat['mean'] - a_lat['mean']) / b_lat['mean'] * 100) if b_lat['mean'] else 0)} |"
    )
    lines.append(
        f"| Latência p95 | {b_lat['p95']:.1f} ms | {a_lat['p95']:.1f} ms | "
        f"{_pct(((b_lat['p95'] - a_lat['p95']) / b_lat['p95'] * 100) if b_lat['p95'] else 0)} |"
    )
    lines.append(
        f"| Decision latency (p95) | — | {with_aion['latency']['decision']['p95']:.2f} ms | novo |"
    )

    # 2. Chamadas LLM / Bypass
    lines.append(
        f"| Chamadas LLM (%) | {baseline['cost']['llm_call_rate']*100:.1f}% | "
        f"{with_aion['cost']['llm_call_rate']*100:.1f}% | "
        f"{_pct(savings['llm_calls_pct_reduction'])} redução |"
    )
    lines.append(
        f"| Bypass rate | {baseline['bypass']['bypass_rate']*100:.1f}% | "
        f"{with_aion['bypass']['bypass_rate']*100:.1f}% | "
        f"{_pct((with_aion['bypass']['bypass_rate'] - baseline['bypass']['bypass_rate']) * 100)} |"
    )

    # 3. Tokens e custo
    lines.append(
        f"| Tokens totais | {baseline['cost']['total_tokens']:,} | "
        f"{with_aion['cost']['total_tokens']:,} | "
        f"{_pct(savings['tokens_pct_reduction'])} redução |"
    )
    lines.append(
        f"| Custo total (USD) | ${baseline['cost']['total_cost_usd']:.4f} | "
        f"${with_aion['cost']['total_cost_usd']:.4f} | "
        f"{_pct(savings['cost_pct_reduction'])} redução |"
    )

    # 4. Qualidade
    b_q = baseline["quality"]["semantic"].get("mean", 0)
    a_q = with_aion["quality"]["semantic"].get("mean", 0)
    delta_q = ((a_q - b_q) / b_q * 100) if b_q else 0
    lines.append(
        f"| Qualidade (semantic mean) | {b_q:.3f} | {a_q:.3f} | {_pct(delta_q)} |"
    )

    b_j = baseline["quality"].get("llm_judge")
    a_j = with_aion["quality"].get("llm_judge")
    if b_j and a_j:
        lines.append(
            f"| Qualidade (LLM-judge) | {b_j['mean']:.3f} | {a_j['mean']:.3f} | "
            f"sample={a_j['samples']} |"
        )

    lines.append("")
    lines.append("")

    # ── Headline sentence ──
    cost_red = savings["cost_pct_reduction"]
    call_red = savings["llm_calls_pct_reduction"]
    qd = ((a_q - b_q) / b_q * 100) if b_q else 0
    if qd >= -5 and cost_red > 0:
        lines.append(
            f"**Resultado**: AION reduziu **{call_red:.1f}%** das chamadas ao LLM, "
            f"economizou **{cost_red:.1f}%** do custo e manteve a qualidade "
            f"({'melhorou' if qd > 2 else '≈ igual'}: {_pct(qd)})."
        )
    else:
        lines.append(
            f"**Resultado**: custos reduziram {cost_red:.1f}% e a qualidade variou {_pct(qd)}. "
            f"Revise o dataset ou os pesos de scoring."
        )
    lines.append("")

    # ── Quality by tier ──
    lines.append("## Qualidade por tier")
    lines.append("")
    lines.append("| Tier | Baseline (mean) | AION (mean) | Amostras |")
    lines.append("|---|---|---|---|")
    for tier, bdata in baseline["quality"]["semantic"].get("by_tier", {}).items():
        adata = with_aion["quality"]["semantic"].get("by_tier", {}).get(tier, {})
        lines.append(
            f"| {tier} | {bdata['mean']:.3f} | "
            f"{adata.get('mean', 0):.3f} | {bdata['samples']} |"
        )
    lines.append("")

    # ── Decision breakdown (only meaningful for AION run) ──
    lines.append("## Decisão (AION)")
    lines.append("")
    actions = with_aion["decision"]["actions"]
    for action, count in sorted(actions.items(), key=lambda x: -x[1]):
        pct = count / with_aion["decision"]["total"] * 100 if with_aion["decision"]["total"] else 0
        lines.append(f"- **{action}**: {count} ({pct:.1f}%)")
    lines.append("")
    conf = with_aion["decision"]["confidence"]
    lines.append(
        f"- Confidence média: **{conf['mean']:.2f}** (mediana {conf['median']:.2f}, "
        f"{conf['samples']} amostras)"
    )
    lines.append("")
    lines.append("### Modelo escolhido por tier")
    lines.append("")
    lines.append("| Tier | Modelo | Requests |")
    lines.append("|---|---|---|")
    for tier, dist in with_aion["decision"]["model_by_tier"].items():
        for model, count in sorted(dist.items(), key=lambda x: -x[1]):
            lines.append(f"| {tier} | {model} | {count} |")
    lines.append("")

    # ── Bypass details ──
    lines.append("## Bypass rate por tier (AION)")
    lines.append("")
    lines.append("| Tier | Bypass rate | Block | CALL_LLM |")
    lines.append("|---|---|---|---|")
    for tier, t in with_aion["bypass"]["by_tier"].items():
        lines.append(
            f"| {tier} | {t['bypass_rate']*100:.1f}% | {t['block']} | {t['call_llm']} |"
        )
    lines.append("")

    # ── Latency detail ──
    lines.append("## Latência detalhada")
    lines.append("")
    lines.append("| Fase | Baseline p50 / p95 / p99 | AION p50 / p95 / p99 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| Total | {b_lat['p50']:.1f} / {b_lat['p95']:.1f} / {b_lat['p99']:.1f} ms | "
        f"{a_lat['p50']:.1f} / {a_lat['p95']:.1f} / {a_lat['p99']:.1f} ms |"
    )
    if with_aion["latency"]["decision"]["samples"] > 0:
        dec = with_aion["latency"]["decision"]
        lines.append(
            f"| Decision (AION) | — | "
            f"{dec['p50']:.2f} / {dec['p95']:.2f} / {dec['p99']:.2f} ms |"
        )
    lines.append("")

    # ── Metodology ──
    lines.append("## Metodologia")
    lines.append("")
    lines.append(f"- Dataset: `benchmarks/datasets/bench_suite.yaml` ({config['n_prompts']} prompts)")
    lines.append(
        f"- Baseline: cada prompt chama o LLM direto "
        f"({'real' if config['live'] else 'mock determinístico'})"
    )
    lines.append(
        f"- Com AION: mesmo prompt passa por ESTIXE → NOMOS → METIS → ExecutionAdapter, "
        f"com cache e routing inteligente."
    )
    lines.append(
        f"- Quality: embedding cosine similarity (primário) "
        f"{' + LLM-as-judge em amostra' if config['llm_judge_sample_rate'] > 0 else ''}"
    )
    lines.append("- Custo: estimativa com `aion.nomos.cost.estimate_request_cost`")
    lines.append("- Latency: `time.perf_counter` nas fronteiras do pipeline e execução")
    lines.append("")

    return "\n".join(lines)
