"""Semantic classifier — detects intents via embedding similarity, NOT pattern matching.

Detects ALL greetings (formal, informal, regional, multilingual) and any
configurable deterministic intents by comparing embeddings with cosine similarity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

from aion.config import EstixeSettings

logger = logging.getLogger("aion.estixe.classifier")


@dataclass
class IntentMatch:
    """Result of intent classification."""
    intent: str
    confidence: float
    matched_example: str
    response_templates: list[str] = field(default_factory=list)
    action: str = "bypass"  # bypass | passthrough | block


@dataclass
class IntentDefinition:
    """An intent loaded from config."""
    name: str
    examples: list[str]
    responses: list[str] = field(default_factory=list)
    action: str = "bypass"
    embeddings: Optional[np.ndarray] = None


class SemanticClassifier:
    """Classifies user input into intents using semantic similarity."""

    def __init__(self, settings: EstixeSettings) -> None:
        self._settings = settings
        self._model = None
        self._intents: list[IntentDefinition] = []
        self._embedding_cache: dict[str, np.ndarray] = {}

    async def load(self) -> None:
        """Load the embedding model and intent definitions."""
        # Load embedding model
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._settings.embedding_model)
            logger.info("Loaded embedding model: %s", self._settings.embedding_model)
        except Exception:
            logger.error("Failed to load embedding model", exc_info=True)
            raise

        # Load intents from YAML
        intents_path = Path(self._settings.intents_path)
        if intents_path.exists():
            await self._load_intents(intents_path)
        else:
            logger.warning("Intents file not found: %s — using empty intent set", intents_path)

    async def _load_intents(self, path: Path) -> None:
        """Load intent definitions and pre-compute embeddings."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        intents_data = data.get("intents", {})
        self._intents = []

        for intent_name, intent_config in intents_data.items():
            examples = intent_config.get("examples", [])
            responses = intent_config.get("responses", [])
            action = intent_config.get("action", "bypass")

            intent = IntentDefinition(
                name=intent_name,
                examples=examples,
                responses=responses,
                action=action,
            )

            # Pre-compute embeddings for all examples
            if examples and self._model:
                intent.embeddings = self._model.encode(
                    examples, convert_to_numpy=True, normalize_embeddings=True
                )

            self._intents.append(intent)

        total_examples = sum(len(i.examples) for i in self._intents)
        logger.info(
            "Loaded %d intents with %d total examples",
            len(self._intents),
            total_examples,
        )

    def classify(self, text: str) -> Optional[IntentMatch]:
        """Classify user input against known intents.

        Returns the best match if confidence >= threshold, else None.
        """
        if not self._model or not self._intents:
            return None

        # Get or cache embedding for input text
        text_lower = text.strip().lower()
        if text_lower in self._embedding_cache:
            input_embedding = self._embedding_cache[text_lower]
        else:
            input_embedding = self._model.encode(
                [text_lower], convert_to_numpy=True, normalize_embeddings=True
            )[0]
            if self._settings.cache_embeddings:
                self._embedding_cache[text_lower] = input_embedding

        best_match: Optional[IntentMatch] = None
        best_confidence = 0.0

        for intent in self._intents:
            if intent.embeddings is None:
                continue

            # Cosine similarity (embeddings are already normalized)
            similarities = intent.embeddings @ input_embedding
            max_idx = int(np.argmax(similarities))
            max_sim = float(similarities[max_idx])

            if max_sim > best_confidence:
                best_confidence = max_sim
                best_match = IntentMatch(
                    intent=intent.name,
                    confidence=max_sim,
                    matched_example=intent.examples[max_idx],
                    response_templates=intent.responses,
                    action=intent.action,
                )

        if best_match and best_match.confidence >= self._settings.bypass_threshold:
            logger.debug(
                "Classified '%s' as '%s' (confidence=%.3f, matched='%s')",
                text_lower,
                best_match.intent,
                best_match.confidence,
                best_match.matched_example,
            )
            return best_match

        return None

    async def reload(self) -> None:
        """Reload intents from config (hot-reload)."""
        self._embedding_cache.clear()
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
