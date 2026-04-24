"""Quality scoring — word-overlap semantic fallback, optional LLM judge."""

from __future__ import annotations

from benchmarks.executors.base import RunResult


def _word_overlap(a: str, b: str) -> float:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


async def quality_stats(
    results: list[RunResult],
    llm_judge_sample_rate: float = 0.0,
) -> dict:
    scores = [_word_overlap(r.response_text, r.expected_pattern) for r in results]
    mean = sum(scores) / len(scores) if scores else 0.0

    return {
        "samples": len(results),
        "semantic": {
            "samples": len(scores),
            "mean": round(mean, 4),
        },
        "llm_judge": None,
    }
