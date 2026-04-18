"""Complexity classifier — hybrid semantic + heuristic scoring.

Two layers:
1. Semantic: embedding similarity to complexity archetypes (weighted 70%)
2. Heuristic: keyword/pattern matching (weighted 30%, fallback if semantic unavailable)

Complexity score ranges from 0 (trivial) to 100 (very complex).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

logger = logging.getLogger("aion.nomos.classifier")


# ── Heuristic patterns (original v1 logic, now secondary signal) ──

_COMPLEXITY_PATTERNS = [
    (r"\b(explain|analyze|compare|evaluate|assess|reason|think|consider)\b", 10),
    (r"\b(why|how does|what if|suppose|assume|hypothetically)\b", 8),
    (r"\b(step by step|first.*then|multiple|several|list all)\b", 12),
    (r"\b(and also|additionally|furthermore|moreover)\b", 5),
    (r"\b(code|function|implement|algorithm|debug|refactor|optimize)\b", 15),
    (r"\b(class|def |import |return |async |await )\b", 15),
    (r"```", 20),
    (r"\b(write|create|generate|compose|draft|design)\b", 10),
    (r"\b(essay|article|story|report|document|specification)\b", 12),
    (r"\b(calculate|compute|solve|prove|derive|formula)\b", 12),
    (r"[+\-*/=<>]{2,}", 5),
    (r"\b(json|xml|yaml|csv|table|format as)\b", 8),
    (r"\b(translate|convert|transform)\b", 8),
]

_SIMPLICITY_PATTERNS = [
    (r"^\w+\?$", -20),
    (r"^(yes|no|ok|sure|thanks)\b", -30),
    (r"^(what is|who is|where is|when was)\b", -10),
]


@dataclass
class ComplexityResult:
    score: float  # 0-100
    factors: list[str]
    semantic_score: Optional[float] = None  # 0-100 (None if unavailable)
    heuristic_score: Optional[float] = None  # 0-100
    method: str = "heuristic"  # "hybrid" | "heuristic" | "semantic"


@dataclass
class _TierArchetype:
    """A complexity tier with pre-computed embeddings."""
    name: str
    score_center: float  # midpoint of score_range
    score_range: tuple[float, float]
    examples: list[str]
    embeddings: Optional[np.ndarray] = None


class ComplexityClassifier:
    """Scores prompt complexity using hybrid semantic + heuristic approach.

    Degrades gracefully: if embedding model is unavailable, falls back to
    pure heuristic (v1 behavior). No feature is lost, only accuracy.
    """

    def __init__(self, *, semantic_weight: float = 0.7) -> None:
        self._semantic_weight = semantic_weight
        self._heuristic_weight = 1.0 - semantic_weight
        self._tiers: list[_TierArchetype] = []
        self._semantic_ready = False

    async def load_archetypes(self, config_dir: Path) -> None:
        """Load complexity archetypes and pre-compute embeddings."""
        archetypes_path = config_dir / "complexity_archetypes.yaml"
        if not archetypes_path.exists():
            logger.warning("Archetypes file not found: %s — using heuristic only", archetypes_path)
            return

        try:
            from aion.shared.embeddings import get_embedding_model
            model = get_embedding_model()
            if not model.loaded:
                await model.load()
        except Exception:
            logger.warning("Embedding model unavailable — using heuristic only", exc_info=True)
            return

        with open(archetypes_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        tiers_data = data.get("tiers", {})
        self._tiers = []

        for tier_name, tier_config in tiers_data.items():
            score_range = tuple(tier_config.get("score_range", [0, 100]))
            score_center = (score_range[0] + score_range[1]) / 2
            examples = tier_config.get("examples", [])

            tier = _TierArchetype(
                name=tier_name,
                score_center=score_center,
                score_range=score_range,
                examples=examples,
            )

            if examples:
                tier.embeddings = model.encode(examples, normalize=True)

            self._tiers.append(tier)

        self._semantic_ready = True
        total_examples = sum(len(t.examples) for t in self._tiers)
        logger.info(
            "Loaded %d complexity tiers with %d archetypes (semantic classification active)",
            len(self._tiers), total_examples,
        )

    def classify(self, messages: list) -> ComplexityResult:
        """Classify complexity using hybrid scoring.

        Returns combined score if semantic is available, heuristic-only otherwise.
        """
        user_message = self._extract_user_message(messages)
        if not user_message:
            return ComplexityResult(score=0, factors=["no_user_message"])

        # Always compute heuristic (fast, no deps)
        heuristic_score, heuristic_factors = self._heuristic_score(user_message, messages)

        # Try semantic
        semantic_score = None
        if self._semantic_ready and self._tiers:
            try:
                semantic_score = self._semantic_score(user_message)
            except Exception:
                logger.debug("Semantic classification failed — using heuristic", exc_info=True)

        # Combine
        if semantic_score is not None:
            final = (self._semantic_weight * semantic_score
                     + self._heuristic_weight * heuristic_score)
            final = max(0, min(100, final))
            factors = heuristic_factors + [f"semantic:{semantic_score:.1f}"]
            method = "hybrid"
        else:
            final = heuristic_score
            factors = heuristic_factors
            method = "heuristic"

        return ComplexityResult(
            score=round(final, 1),
            factors=factors,
            semantic_score=round(semantic_score, 1) if semantic_score is not None else None,
            heuristic_score=round(heuristic_score, 1),
            method=method,
        )

    def _semantic_score(self, text: str) -> float:
        """Score via embedding similarity to tier archetypes."""
        from aion.shared.embeddings import get_embedding_model
        model = get_embedding_model()

        input_emb = model.encode_single(text, normalize=True)

        # Compute max similarity per tier
        tier_scores: list[tuple[float, float]] = []  # (similarity, score_center)
        for tier in self._tiers:
            if tier.embeddings is None:
                continue
            similarities = tier.embeddings @ input_emb
            max_sim = float(np.max(similarities))
            tier_scores.append((max_sim, tier.score_center))

        if not tier_scores:
            return 50.0  # neutral

        # Weighted interpolation: each tier's center weighted by its similarity
        total_weight = sum(sim for sim, _ in tier_scores)
        if total_weight <= 0:
            return 50.0

        weighted_score = sum(sim * center for sim, center in tier_scores) / total_weight
        return max(0, min(100, weighted_score))

    @staticmethod
    def _heuristic_score(user_message: str, messages: list) -> tuple[float, list[str]]:
        """Original v1 heuristic scoring."""
        score = 0.0
        factors = []

        word_count = len(user_message.split())
        if word_count > 200:
            score += 20
            factors.append(f"long_prompt({word_count}w)")
        elif word_count > 50:
            score += 10
            factors.append(f"medium_prompt({word_count}w)")
        elif word_count < 5:
            score -= 10
            factors.append(f"short_prompt({word_count}w)")

        text_lower = user_message.lower()
        for pattern, weight in _COMPLEXITY_PATTERNS:
            if re.search(pattern, text_lower):
                score += weight
                factors.append(f"pattern:{pattern[:20]}")

        for pattern, weight in _SIMPLICITY_PATTERNS:
            if re.search(pattern, text_lower):
                score += weight
                factors.append(f"simple:{pattern[:20]}")

        msg_count = len(messages)
        if msg_count > 10:
            score += 10
            factors.append(f"long_conversation({msg_count})")

        for msg in messages:
            role = msg.role if hasattr(msg, "role") else msg.get("role", "")
            content = (msg.content if hasattr(msg, "content") else msg.get("content", "")) or ""
            if role == "system" and len(content) > 500:
                score += 10
                factors.append("complex_system_prompt")
                break

        score = max(0, min(100, score))
        return score, factors

    @staticmethod
    def _extract_user_message(messages: list) -> str:
        """Get the last user message from the conversation."""
        for msg in reversed(messages):
            role = msg.role if hasattr(msg, "role") else msg.get("role", "")
            content = (msg.content if hasattr(msg, "content") else msg.get("content", "")) or ""
            if role == "user":
                return content
        return ""
