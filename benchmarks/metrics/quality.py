"""Pillar 4 — quality scoring (semantic similarity + optional LLM-as-judge).

Hybrid approach:
- Semantic similarity via sentence-transformers (reuses ESTIXE's embedding model)
- LLM-as-judge on a configurable sample (default 10%) — only if --llm-judge flag set
"""

from __future__ import annotations

import logging
import random
import statistics
from typing import Iterable

from benchmarks.executors.base import RunResult

logger = logging.getLogger("benchmarks.metrics.quality")

_model = None
_model_name = "all-MiniLM-L6-v2"


def _get_model():
    """Lazy-load sentence-transformers model. Returns None if unavailable."""
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_model_name)
        logger.info("quality: loaded embedding model %s", _model_name)
    except Exception as exc:
        logger.warning("quality: embedding model unavailable (%s)", exc)
        _model = False  # sentinel to avoid retrying
    return _model if _model else None


def _cosine(a, b) -> float:
    import numpy as np
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _semantic_score(response: str, expected: str) -> float:
    """Return cosine similarity between response and expected (0.0-1.0)."""
    if not response or not expected:
        return 0.0 if not response else 1.0 if response == expected else 0.0
    model = _get_model()
    if model is None:
        # Fallback: character-overlap Jaccard (very rough)
        ra = set(response.lower().split())
        eb = set(expected.lower().split())
        if not ra or not eb:
            return 0.0
        return round(len(ra & eb) / len(ra | eb), 3)
    try:
        emb_response = model.encode([response], convert_to_numpy=True, normalize_embeddings=True)[0]
        emb_expected = model.encode([expected], convert_to_numpy=True, normalize_embeddings=True)[0]
        # Normalized embeddings: dot product == cosine similarity
        import numpy as np
        sim = float(np.dot(emb_response, emb_expected))
        return max(0.0, min(1.0, (sim + 1.0) / 2.0))  # map [-1, 1] -> [0, 1]
    except Exception as exc:
        logger.debug("quality embedding failed: %s", exc)
        return 0.0


async def _llm_judge(response: str, expected: str, prompt: str) -> float:
    """Call a small LLM to score 0-10; returns normalized [0, 1]. Async."""
    try:
        from aion.config import get_settings
        from aion.proxy import forward_request
        from aion.shared.schemas import (
            ChatCompletionRequest,
            ChatMessage,
            PipelineContext,
        )
        settings = get_settings()
        judge_prompt = (
            "You are a strict evaluator. Score how well 'RESPONSE' matches "
            "'EXPECTED' on a scale of 0 to 10. Only reply with a single integer.\n\n"
            f"PROMPT: {prompt}\n"
            f"EXPECTED: {expected}\n"
            f"RESPONSE: {response}\n"
            "SCORE:"
        )
        req = ChatCompletionRequest(
            model="gpt-4o-mini",
            messages=[ChatMessage(role="user", content=judge_prompt)],
            max_tokens=5,
            temperature=0.0,
        )
        ctx = PipelineContext(
            tenant="bench-judge",
            selected_model="gpt-4o-mini",
            selected_provider="openai",
        )
        response = await forward_request(req, ctx, settings)
        text = response.choices[0].message.content if response.choices else "0"
        # Extract first integer
        import re
        m = re.search(r"\d+", text)
        if not m:
            return 0.0
        score = min(10, max(0, int(m.group(0))))
        return score / 10.0
    except Exception as exc:
        logger.debug("llm_judge failed: %s", exc)
        return -1.0  # signal "no data"


async def quality_stats(
    results: Iterable[RunResult],
    *,
    llm_judge_sample_rate: float = 0.0,  # 0 means off; 0.1 means 10% sample
    seed: int = 42,
) -> dict:
    results = list(results)
    if not results:
        return {"semantic": {}, "llm_judge": None, "samples": 0}

    # 1) Semantic similarity on ALL
    semantic_scores: list[float] = []
    per_tier: dict[str, list[float]] = {}
    for r in results:
        if not r.expected_pattern:
            continue
        score = _semantic_score(r.response_text, r.expected_pattern)
        semantic_scores.append(score)
        per_tier.setdefault(r.tier, []).append(score)

    semantic = {
        "mean": round(statistics.mean(semantic_scores), 3) if semantic_scores else 0.0,
        "median": round(statistics.median(semantic_scores), 3) if semantic_scores else 0.0,
        "samples": len(semantic_scores),
        "by_tier": {
            tier: {
                "mean": round(statistics.mean(scores), 3),
                "samples": len(scores),
            }
            for tier, scores in per_tier.items()
        },
    }

    # 2) LLM-as-judge on sample
    llm_judge_report = None
    if llm_judge_sample_rate > 0:
        rng = random.Random(seed)
        sample = [r for r in results if r.expected_pattern]
        k = max(1, int(len(sample) * llm_judge_sample_rate))
        sampled = rng.sample(sample, k=min(k, len(sample)))
        scores = []
        for r in sampled:
            s = await _llm_judge(r.response_text, r.expected_pattern, r.prompt)
            if s >= 0:
                scores.append(s)
        if scores:
            llm_judge_report = {
                "mean": round(statistics.mean(scores), 3),
                "samples": len(scores),
                "sample_rate": llm_judge_sample_rate,
            }

    return {
        "semantic": semantic,
        "llm_judge": llm_judge_report,
        "samples": len(results),
    }
