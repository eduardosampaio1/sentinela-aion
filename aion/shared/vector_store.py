"""FAISS-backed vector store with per-tenant isolation.

Provides semantic search for: cache, intent matching, complexity classification.
Degrades silently if FAISS is unavailable — callers get empty results, never errors.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("aion.shared.vector_store")

# Try to import FAISS — graceful degradation if not installed
try:
    import faiss
    _FAISS_AVAILABLE = True
except ImportError:
    faiss = None  # type: ignore[assignment]
    _FAISS_AVAILABLE = False
    logger.warning("faiss-cpu not installed — vector store disabled, fallback active")


@dataclass
class SearchResult:
    """A single search result from the vector store."""
    id: str
    score: float  # cosine similarity (0-1 for normalized vectors)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorStoreStats:
    """Stats for a single tenant store."""
    count: int
    max_capacity: int
    oldest_entry_age_seconds: float
    healthy: bool


class TenantVectorStore:
    """FAISS index + metadata for a single tenant. Thread-safe.

    Stores vectors alongside metadata so we never need to extract from FAISS internals.
    On removal, rebuilds the index from our stored vectors (acceptable at <10k scale).
    """

    def __init__(self, dimension: int, max_vectors: int = 10_000) -> None:
        self._dimension = dimension
        self._max_vectors = max_vectors
        self._lock = threading.Lock()

        # Our source of truth: stored vectors + metadata
        self._vectors: list[np.ndarray] = []
        self._entries: list[dict[str, Any]] = []  # {id, metadata, timestamp}
        self._id_to_pos: dict[str, int] = {}

        # FAISS index (mirror of _vectors, for fast search only)
        self._index = self._new_index()

    def _new_index(self):
        """Create a fresh FAISS index."""
        if _FAISS_AVAILABLE:
            return faiss.IndexFlatIP(self._dimension)
        return None

    @property
    def count(self) -> int:
        return len(self._entries)

    @property
    def healthy(self) -> bool:
        return _FAISS_AVAILABLE and self._index is not None

    def add(self, id: str, embedding: np.ndarray, metadata: dict[str, Any] | None = None) -> bool:
        """Add a vector with metadata. Returns True if added, False on error.

        If id already exists, updates it. Evicts oldest entry if at capacity.
        """
        if not self.healthy:
            return False

        vec = embedding.reshape(-1).astype(np.float32)

        with self._lock:
            # Update: remove old then re-add
            if id in self._id_to_pos:
                self._remove_locked(id)

            # Evict oldest if at capacity
            if len(self._entries) >= self._max_vectors:
                self._evict_oldest_locked()

            # Store vector + metadata
            pos = len(self._entries)
            self._vectors.append(vec.copy())
            self._entries.append({
                "id": id,
                "metadata": metadata or {},
                "timestamp": time.time(),
            })
            self._id_to_pos[id] = pos

            # Add to FAISS index
            self._index.add(vec.reshape(1, -1))
            return True

    def search(
        self,
        query_embedding: np.ndarray,
        k: int = 5,
        threshold: float = 0.0,
    ) -> list[SearchResult]:
        """Search for similar vectors. Returns results above threshold, sorted by score."""
        if not self.healthy or self._index.ntotal == 0:
            return []

        vec = query_embedding.reshape(1, -1).astype(np.float32)
        actual_k = min(k, self._index.ntotal)

        scores, indices = self._index.search(vec, actual_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._entries):
                continue
            if float(score) < threshold:
                continue
            entry = self._entries[idx]
            results.append(SearchResult(
                id=entry["id"],
                score=float(score),
                metadata=entry["metadata"],
            ))

        return results

    def remove(self, id: str) -> bool:
        """Remove a vector by id. Returns True if found and removed."""
        if not self.healthy:
            return False
        with self._lock:
            return self._remove_locked(id)

    def _remove_locked(self, id: str) -> bool:
        """Remove entry and rebuild FAISS index. Caller must hold lock."""
        if id not in self._id_to_pos:
            return False

        # Remove from our lists
        pos = self._id_to_pos[id]
        self._vectors.pop(pos)
        self._entries.pop(pos)

        # Rebuild position map
        self._id_to_pos.clear()
        for i, entry in enumerate(self._entries):
            self._id_to_pos[entry["id"]] = i

        # Rebuild FAISS index from stored vectors
        self._index = self._new_index()
        if self._vectors:
            matrix = np.array(self._vectors, dtype=np.float32)
            self._index.add(matrix)

        return True

    def _evict_oldest_locked(self) -> None:
        """Evict the oldest entry. Caller must hold lock."""
        if not self._entries:
            return
        oldest_idx = min(range(len(self._entries)), key=lambda i: self._entries[i]["timestamp"])
        oldest_id = self._entries[oldest_idx]["id"]
        self._remove_locked(oldest_id)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._vectors.clear()
            self._entries.clear()
            self._id_to_pos.clear()
            self._index = self._new_index()

    def stats(self) -> VectorStoreStats:
        now = time.time()
        oldest_age = 0.0
        if self._entries:
            oldest_ts = min(e["timestamp"] for e in self._entries)
            oldest_age = now - oldest_ts
        return VectorStoreStats(
            count=self.count,
            max_capacity=self._max_vectors,
            oldest_entry_age_seconds=oldest_age,
            healthy=self.healthy,
        )


class VectorStoreManager:
    """Manages per-tenant vector stores. Thread-safe factory."""

    def __init__(
        self,
        dimension: int,
        max_per_tenant: int = 10_000,
        max_total: int = 100_000,
    ) -> None:
        self._dimension = dimension
        self._max_per_tenant = max_per_tenant
        self._max_total = max_total
        self._stores: dict[str, TenantVectorStore] = {}
        self._lock = threading.Lock()

    def get_store(self, tenant: str) -> TenantVectorStore:
        """Get or create a vector store for a tenant."""
        if tenant in self._stores:
            return self._stores[tenant]
        with self._lock:
            if tenant not in self._stores:
                self._stores[tenant] = TenantVectorStore(
                    dimension=self._dimension,
                    max_vectors=self._max_per_tenant,
                )
                logger.debug("Created vector store for tenant '%s'", tenant)
            return self._stores[tenant]

    def delete_tenant(self, tenant: str) -> bool:
        """Delete a tenant's vector store (LGPD). Returns True if existed."""
        with self._lock:
            if tenant in self._stores:
                self._stores[tenant].clear()
                del self._stores[tenant]
                logger.info("Deleted vector store for tenant '%s'", tenant)
                return True
            return False

    @property
    def total_vectors(self) -> int:
        return sum(s.count for s in self._stores.values())

    @property
    def tenant_count(self) -> int:
        return len(self._stores)

    def healthy(self) -> bool:
        """Global health check — True if FAISS is available."""
        return _FAISS_AVAILABLE

    def all_stats(self) -> dict[str, VectorStoreStats]:
        return {tenant: store.stats() for tenant, store in self._stores.items()}


# ── Singleton ──

_manager: Optional[VectorStoreManager] = None


def get_vector_store_manager(dimension: int = 384) -> VectorStoreManager:
    """Get the shared VectorStoreManager singleton.

    Dimension defaults to 384 (all-MiniLM-L6-v2). Updated on first call
    when the embedding model reports its actual dimension.
    """
    global _manager
    if _manager is None:
        _manager = VectorStoreManager(
            dimension=dimension,
            max_per_tenant=10_000,
            max_total=100_000,
        )
    return _manager
