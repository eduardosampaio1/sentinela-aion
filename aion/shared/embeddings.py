"""Shared embedding model singleton — single source of truth for all modules.

Loaded once at startup, reused by ESTIXE (intent matching), semantic cache,
and NOMOS (semantic complexity classification). Thread-safe for reads.
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from typing import Optional

import numpy as np

from aion.config import get_estixe_settings

logger = logging.getLogger("aion.shared.embeddings")

_LRU_MAX_SIZE = 5000


class EmbeddingModel:
    """Singleton wrapper around SentenceTransformer with LRU cache."""

    def __init__(self) -> None:
        self._model = None
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._loaded = False
        self._load_failed = False  # True if load was attempted but failed
        self._model_name: str = ""

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        """Embedding dimension (e.g. 384 for MiniLM)."""
        if not self._loaded or self._model is None:
            return 0
        return self._model.get_sentence_embedding_dimension()

    async def load(self) -> None:
        """Load the sentence-transformers model. Idempotent.

        Does NOT raise on failure — sets _load_failed=True instead.
        Callers check .loaded before using encode/encode_single.
        This ensures that modules depending on embeddings degrade gracefully
        (bypass/cache disabled) instead of crashing the entire pipeline.
        """
        if self._loaded or self._load_failed:
            return
        settings = get_estixe_settings()
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(
                "Carregando modelo '%s' (primeira execucao: ~150 MB, pode demorar 2-3 min)...",
                settings.embedding_model,
            )
            self._model = SentenceTransformer(settings.embedding_model)
            self._model_name = settings.embedding_model
            self._loaded = True
            logger.info(
                "Embedding model loaded: %s (dim=%d)",
                self._model_name,
                self.dimension,
            )
        except ImportError:
            self._load_failed = True
            logger.warning(
                "sentence-transformers not installed — semantic features disabled "
                "(bypass, cache, semantic classification). Install with: pip install sentence-transformers"
            )
        except Exception:
            self._load_failed = True
            logger.error("Failed to load embedding model — semantic features disabled", exc_info=True)

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray:
        """Encode texts into embeddings. Returns (N, dim) array."""
        if not self._loaded or self._model is None:
            raise RuntimeError("Embedding model not loaded — call load() first")
        return self._model.encode(
            texts, convert_to_numpy=True, normalize_embeddings=normalize,
        )

    def encode_single(self, text: str, *, normalize: bool = True, use_cache: bool = True) -> np.ndarray:
        """Encode a single text with LRU caching. Returns (dim,) array."""
        if not self._loaded or self._model is None:
            raise RuntimeError("Embedding model not loaded — call load() first")

        text_lower = text.strip().lower()
        cache_key = hashlib.sha256(text_lower.encode()).hexdigest()

        # Cache hit
        if use_cache and cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        # Encode
        embedding = self._model.encode(
            [text_lower], convert_to_numpy=True, normalize_embeddings=normalize,
        )[0]

        # Cache store
        if use_cache:
            self._cache[cache_key] = embedding
            while len(self._cache) > _LRU_MAX_SIZE:
                self._cache.popitem(last=False)

        return embedding

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        self._cache.clear()


# ── Singleton ──

_instance: Optional[EmbeddingModel] = None


def get_embedding_model() -> EmbeddingModel:
    """Get the shared embedding model singleton."""
    global _instance
    if _instance is None:
        _instance = EmbeddingModel()
    return _instance
