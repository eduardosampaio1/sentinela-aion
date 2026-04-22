"""Seed quality diagnostic for risk_taxonomy.yaml.

Detecta problemas no conjunto de seeds antes de ir para produção:

  REDUNDÂNCIA   — seeds dentro da mesma categoria com similarity > threshold_redundancy
                  → pode remover sem perder cobertura

  CONFUSÃO      — seeds de categorias DIFERENTES com similarity > threshold_confusion
                  → risco de misclassificação: o input "parece" com a categoria errada

  ESPARSIDADE   — par de seeds na mesma categoria com similarity máxima < threshold_sparse
                  → seeds podem ser semânticamente desconexos (não coesos)

Usage:
    python -m aion.estixe.tools.seed_quality
    python -m aion.estixe.tools.seed_quality --taxonomy path/to/risk_taxonomy.yaml
    python -m aion.estixe.tools.seed_quality --redundancy 0.92 --confusion 0.85 --sparse 0.45

Output: relatório textual para terminal. Sem escrita em disco.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import numpy as np
import yaml


# ── Default thresholds ──────────────────────────────────────────────────────
DEFAULT_REDUNDANCY = 0.92   # seeds "duplicados" — mesma semântica, um pode ser removido
DEFAULT_CONFUSION  = 0.85   # seeds de categorias diferentes muito parecidos
DEFAULT_SPARSE     = 0.45   # coesão mínima esperada dentro de uma categoria


def _load_taxonomy(path: Path) -> dict[str, dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("risks", {})


async def _encode_all(risks: dict[str, dict]) -> dict[str, np.ndarray]:
    """Encode seeds for all risk categories. Returns {category: embeddings_matrix}."""
    from aion.estixe._normalize import normalize_input
    from aion.shared.embeddings import get_embedding_model

    model = get_embedding_model()
    if not model.loaded:
        await model.load()
    if not model.loaded:
        print("[ERROR] Embedding model failed to load. Aborting.", file=sys.stderr)
        sys.exit(1)

    embeddings: dict[str, np.ndarray] = {}
    for name, cfg in risks.items():
        seeds = cfg.get("seeds", [])
        if seeds:
            normalized = [normalize_input(s) for s in seeds]
            embeddings[name] = model.encode(normalized, normalize=True)
    return embeddings


def _check_redundancy(
    risks: dict[str, dict],
    embeddings: dict[str, np.ndarray],
    threshold: float,
) -> list[tuple[str, str, str, float]]:
    """Return list of (category, seed_a, seed_b, similarity) for redundant pairs."""
    issues = []
    for name, cfg in risks.items():
        seeds = cfg.get("seeds", [])
        embs = embeddings.get(name)
        if embs is None or len(seeds) < 2:
            continue
        sim_matrix = embs @ embs.T  # (N, N) pairwise cosine similarity
        n = len(seeds)
        for i in range(n):
            for j in range(i + 1, n):
                sim = float(sim_matrix[i, j])
                if sim >= threshold:
                    issues.append((name, seeds[i], seeds[j], sim))
    return sorted(issues, key=lambda x: -x[3])


def _check_confusion(
    risks: dict[str, dict],
    embeddings: dict[str, np.ndarray],
    threshold: float,
) -> list[tuple[str, str, str, str, float]]:
    """Return list of (cat_a, seed_a, cat_b, seed_b, similarity) for cross-category confusion."""
    issues = []
    categories = list(risks.keys())
    for i, cat_a in enumerate(categories):
        seeds_a = risks[cat_a].get("seeds", [])
        embs_a = embeddings.get(cat_a)
        if embs_a is None:
            continue
        for j in range(i + 1, len(categories)):
            cat_b = categories[j]
            seeds_b = risks[cat_b].get("seeds", [])
            embs_b = embeddings.get(cat_b)
            if embs_b is None:
                continue
            # cross-matrix: (len_a, len_b)
            cross = embs_a @ embs_b.T
            idx_flat = int(np.argmax(cross))
            row, col = divmod(idx_flat, len(seeds_b))
            max_sim = float(cross[row, col])
            if max_sim >= threshold:
                issues.append((cat_a, seeds_a[row], cat_b, seeds_b[col], max_sim))
    return sorted(issues, key=lambda x: -x[4])


def _check_sparsity(
    risks: dict[str, dict],
    embeddings: dict[str, np.ndarray],
    threshold: float,
) -> list[tuple[str, float, float]]:
    """Return list of (category, min_pairwise_sim, max_pairwise_sim) for sparse categories."""
    issues = []
    for name, cfg in risks.items():
        seeds = cfg.get("seeds", [])
        embs = embeddings.get(name)
        if embs is None or len(seeds) < 2:
            continue
        sim_matrix = embs @ embs.T
        n = len(seeds)
        off_diagonal = [float(sim_matrix[i, j]) for i in range(n) for j in range(i + 1, n)]
        if not off_diagonal:
            continue
        avg_sim = float(np.mean(off_diagonal))
        min_sim = float(np.min(off_diagonal))
        if avg_sim < threshold:
            issues.append((name, min_sim, avg_sim))
    return sorted(issues, key=lambda x: x[2])  # lowest avg first


def _print_section(title: str, count: int) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}  ({count} item(s))")
    print(f"{'=' * 60}")


def run_report(
    taxonomy_path: Path,
    threshold_redundancy: float = DEFAULT_REDUNDANCY,
    threshold_confusion: float = DEFAULT_CONFUSION,
    threshold_sparse: float = DEFAULT_SPARSE,
) -> None:
    """Main entry point — loads taxonomy, encodes seeds, prints report."""
    risks = _load_taxonomy(taxonomy_path)
    total_seeds = sum(len(c.get("seeds", [])) for c in risks.values())

    print(f"\nSeed Quality Diagnostic — {taxonomy_path.name}")
    print(f"  Categories : {len(risks)}")
    print(f"  Total seeds: {total_seeds}")
    print(f"  Thresholds : redundancy={threshold_redundancy}, "
          f"confusion={threshold_confusion}, sparsity<{threshold_sparse}")

    embeddings = asyncio.run(_encode_all(risks))

    # ── Redundancy ───────────────────────────────────────────────────────────
    redundant = _check_redundancy(risks, embeddings, threshold_redundancy)
    _print_section("REDUNDANT SEEDS (same category, high similarity)", len(redundant))
    if redundant:
        for cat, s_a, s_b, sim in redundant[:20]:  # cap display at 20
            print(f"  [{cat}]  {sim:.3f}")
            print(f"    A: {s_a}")
            print(f"    B: {s_b}")
    else:
        print("  OK - No redundant seed pairs found.")

    # ── Cross-category confusion ─────────────────────────────────────────────
    confused = _check_confusion(risks, embeddings, threshold_confusion)
    _print_section("CROSS-CATEGORY CONFUSION (different categories, high similarity)", len(confused))
    if confused:
        for cat_a, s_a, cat_b, s_b, sim in confused[:20]:
            print(f"  {sim:.3f}  [{cat_a}] <-> [{cat_b}]")
            print(f"    {cat_a}: {s_a}")
            print(f"    {cat_b}: {s_b}")
    else:
        print("  OK - No cross-category confusion found.")

    # ── Sparsity ─────────────────────────────────────────────────────────────
    sparse = _check_sparsity(risks, embeddings, threshold_sparse)
    _print_section(f"SPARSE CATEGORIES (avg intra-category sim < {threshold_sparse})", len(sparse))
    if sparse:
        for cat, min_sim, avg_sim in sparse:
            print(f"  [{cat}]  avg={avg_sim:.3f}  min={min_sim:.3f}")
            seed_count = len(risks[cat].get("seeds", []))
            print(f"    {seed_count} seeds — seeds may need review for semantic coherence")
    else:
        print("  OK - All categories have acceptable intra-category coherence.")

    # ── Summary ──────────────────────────────────────────────────────────────
    total_issues = len(redundant) + len(confused) + len(sparse)
    print(f"\n{'-' * 60}")
    print(f"  SUMMARY: {total_issues} issue(s) found")
    print(f"    Redundant  : {len(redundant)}")
    print(f"    Confused   : {len(confused)}")
    print(f"    Sparse     : {len(sparse)}")
    if total_issues == 0:
        print("  OK - Taxonomy is clean.")
    print(f"{'-' * 60}\n")


def _default_taxonomy_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "risk_taxonomy.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed quality diagnostic for risk_taxonomy.yaml",
    )
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=_default_taxonomy_path(),
        help="Path to risk_taxonomy.yaml (default: estixe/data/risk_taxonomy.yaml)",
    )
    parser.add_argument(
        "--redundancy",
        type=float,
        default=DEFAULT_REDUNDANCY,
        help=f"Similarity threshold for intra-category redundancy (default: {DEFAULT_REDUNDANCY})",
    )
    parser.add_argument(
        "--confusion",
        type=float,
        default=DEFAULT_CONFUSION,
        help=f"Similarity threshold for cross-category confusion (default: {DEFAULT_CONFUSION})",
    )
    parser.add_argument(
        "--sparse",
        type=float,
        default=DEFAULT_SPARSE,
        help=f"Min avg similarity threshold for sparsity check (default: {DEFAULT_SPARSE})",
    )
    args = parser.parse_args()

    if not args.taxonomy.exists():
        print(f"[ERROR] Taxonomy file not found: {args.taxonomy}", file=sys.stderr)
        sys.exit(1)

    run_report(
        taxonomy_path=args.taxonomy,
        threshold_redundancy=args.redundancy,
        threshold_confusion=args.confusion,
        threshold_sparse=args.sparse,
    )


if __name__ == "__main__":
    main()
