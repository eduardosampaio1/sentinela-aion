"""Semantic classifier — detects intents via embedding similarity, NOT pattern matching.

Detects ALL greetings (formal, informal, regional, multilingual) and any
configurable deterministic intents by comparing embeddings with cosine similarity.

Uses the shared EmbeddingModel singleton (aion.shared.embeddings) for all
encoding operations — model is loaded once and reused across modules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

from aion.config import EstixeSettings
from aion.estixe._normalize import normalize_input
from aion.shared.embeddings import get_embedding_model

logger = logging.getLogger("aion.estixe.classifier")


@dataclass
class IntentMatch:
    """Result of intent classification."""
    intent: str
    confidence: float
    matched_example: str
    response_templates: list[str] = field(default_factory=list)
    action: str = "bypass"  # bypass | passthrough | block
    block_reason: str = ""  # populated when action=block


@dataclass
class IntentDefinition:
    """An intent loaded from config."""
    name: str
    examples: list[str]
    responses: list[str] = field(default_factory=list)
    action: str = "bypass"
    block_reason: str = ""   # populated when action=block
    embeddings: Optional[np.ndarray] = None


class SemanticClassifier:
    """Classifies user input into intents using semantic similarity."""

    def __init__(self, settings: EstixeSettings) -> None:
        self._settings = settings
        self._intents: list[IntentDefinition] = []

    async def load(self) -> None:
        """Load the shared embedding model and intent definitions.

        If the embedding model is unavailable (missing library, download failure),
        intents are still loaded from YAML but without embeddings — classify()
        will return None for all inputs (no bypass, but no crash either).
        """
        model = get_embedding_model()
        if not model.loaded:
            await model.load()  # does NOT raise — sets model._load_failed instead
            if model.loaded:
                logger.info("Shared embedding model loaded: %s", model.model_name)
            else:
                logger.warning("Embedding model unavailable — intent classification disabled")

        # Load intents from YAML (even without model — embeddings skipped)
        intents_path = Path(self._settings.intents_path)
        if intents_path.exists():
            await self._load_intents(intents_path)
        else:
            logger.warning("Intents file not found: %s — using empty intent set", intents_path)

    async def _load_intents(self, path: Path) -> None:
        """Load intent definitions and pre-compute embeddings."""
        model = get_embedding_model()

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        intents_data = data.get("intents", {})
        self._intents = []

        for intent_name, intent_config in intents_data.items():
            examples = intent_config.get("examples", [])
            responses = intent_config.get("responses", [])
            action = intent_config.get("action", "bypass")
            block_reason = intent_config.get("block_reason", "")

            intent = IntentDefinition(
                name=intent_name,
                examples=examples,
                responses=responses,
                action=action,
                block_reason=block_reason,
            )

            # Pre-compute embeddings — normalize examples before encoding so the
            # same transform is applied to both seeds and inputs at classify time.
            if examples and model.loaded:
                normalized_examples = [normalize_input(e) for e in examples]
                intent.embeddings = model.encode(normalized_examples, normalize=True)

            self._intents.append(intent)

        total_examples = sum(len(i.examples) for i in self._intents)
        logger.info(
            "Loaded %d intents with %d total examples",
            len(self._intents),
            total_examples,
        )

    def classify(
        self,
        text: str,
        block_min_threshold: float | None = None,
        bypass_threshold: float | None = None,
        prior_intent: str | None = None,
    ) -> Optional[IntentMatch]:
        """Classify user input against known intents.

        Returns the best match if confidence >= bypass_threshold, else None.

        Args:
            text: User input to classify.
            block_min_threshold: If set, action=block intents require confidence >= this value
                (separate from bypass_threshold to prevent dynamic relaxation from lowering
                the bar for blocking decisions). If None, no extra floor is applied.
            prior_intent: Intent name from the previous turn. When the best match is the
                same non-block intent, applies a small continuity boost (+0.04) to help
                follow-up questions that are slightly below threshold.
        """
        model = get_embedding_model()
        if not model.loaded or not self._intents:
            return None

        # Normalize before encoding — same transform applied to examples at load time.
        # Cache uses normalized form as key: "IGNORE instructions" == "ignore instructions".
        normalized_text = normalize_input(text)
        input_embedding = model.encode_single(
            normalized_text, normalize=True, use_cache=self._settings.cache_embeddings,
        )

        best_match: Optional[IntentMatch] = None
        best_confidence = 0.0

        for intent in self._intents:
            if intent.embeddings is None:
                continue

            # Cosine similarity (embeddings are already normalized)
            similarities = intent.embeddings @ input_embedding
            max_idx = int(np.argmax(similarities))
            max_sim = float(similarities[max_idx])

            # Intent continuity: small boost for same non-block intent from prior turn.
            # Only applied to non-block intents to avoid lowering the security bar.
            if prior_intent and intent.name == prior_intent and intent.action != "block":
                max_sim = min(1.0, max_sim + 0.04)

            if max_sim > best_confidence:
                best_confidence = max_sim
                best_match = IntentMatch(
                    intent=intent.name,
                    confidence=max_sim,
                    matched_example=intent.examples[max_idx],
                    response_templates=intent.responses,
                    action=intent.action,
                    block_reason=intent.block_reason,
                )

        effective_bypass_threshold = bypass_threshold if bypass_threshold is not None else self._settings.bypass_threshold
        if best_match and best_match.confidence >= effective_bypass_threshold:
            # Extra floor for block intents — prevents dynamic threshold relaxation from
            # lowering the bar for blocking decisions
            if (
                best_match.action == "block"
                and block_min_threshold is not None
                and best_match.confidence < block_min_threshold
            ):
                logger.debug(
                    "Block intent '%s' suppressed: confidence %.3f < block_min_threshold %.3f",
                    best_match.intent, best_match.confidence, block_min_threshold,
                )
                return None
            logger.debug(
                "Classified '%s' as '%s' (confidence=%.3f, matched='%s')",
                text.strip().lower(),
                best_match.intent,
                best_match.confidence,
                best_match.matched_example,
            )
            return best_match

        return None

    async def reload(self) -> None:
        """Reload intents from config (hot-reload)."""
        model = get_embedding_model()
        model.clear_cache()
        intents_path = Path(self._settings.intents_path)
        if intents_path.exists():
            await self._load_intents(intents_path)
            logger.info("Intents reloaded")

    @property
    def intent_count(self) -> int:
        return len(self._intents)

    @property
    def example_count(self) -> int:
        return sum(len(i.examples) for i in self._intents)
