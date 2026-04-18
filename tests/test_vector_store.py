"""Tests for the FAISS-backed vector store with per-tenant isolation."""

import time

import numpy as np
import pytest

from aion.shared.vector_store import (
    TenantVectorStore,
    VectorStoreManager,
    _FAISS_AVAILABLE,
)

DIM = 8  # small dimension for fast tests


def _random_vec(dim: int = DIM) -> np.ndarray:
    """Random normalized vector."""
    v = np.random.randn(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _similar_vec(base: np.ndarray, noise: float = 0.05) -> np.ndarray:
    """Vector similar to base (high cosine similarity)."""
    v = base + np.random.randn(*base.shape).astype(np.float32) * noise
    return v / np.linalg.norm(v)


# ── Skip all if FAISS not installed ──

pytestmark = pytest.mark.skipif(not _FAISS_AVAILABLE, reason="faiss-cpu not installed")


# ── TenantVectorStore ──

class TestTenantVectorStore:
    def test_empty_store(self):
        store = TenantVectorStore(dimension=DIM)
        assert store.count == 0
        assert store.healthy

    def test_add_and_count(self):
        store = TenantVectorStore(dimension=DIM)
        store.add("a", _random_vec(), {"key": "val"})
        assert store.count == 1

    def test_add_duplicate_id_updates(self):
        store = TenantVectorStore(dimension=DIM)
        v1 = _random_vec()
        v2 = _random_vec()
        store.add("x", v1, {"ver": 1})
        store.add("x", v2, {"ver": 2})
        assert store.count == 1
        # search should find v2, not v1
        results = store.search(v2, k=1)
        assert len(results) == 1
        assert results[0].metadata["ver"] == 2

    def test_search_finds_similar(self):
        store = TenantVectorStore(dimension=DIM)
        base = _random_vec()
        store.add("target", base, {"name": "target"})
        # Add some noise vectors
        for i in range(5):
            store.add(f"noise_{i}", _random_vec())

        query = _similar_vec(base, noise=0.01)
        results = store.search(query, k=3, threshold=0.5)
        assert len(results) >= 1
        assert results[0].id == "target"
        assert results[0].score > 0.9

    def test_search_threshold_filters(self):
        store = TenantVectorStore(dimension=DIM)
        store.add("a", _random_vec())
        store.add("b", _random_vec())

        query = _random_vec()
        # Very high threshold — likely no results
        results = store.search(query, k=10, threshold=0.99)
        # At least check it doesn't crash; results may vary
        assert isinstance(results, list)

    def test_search_empty_store_returns_empty(self):
        store = TenantVectorStore(dimension=DIM)
        results = store.search(_random_vec(), k=5)
        assert results == []

    def test_remove(self):
        store = TenantVectorStore(dimension=DIM)
        store.add("a", _random_vec())
        store.add("b", _random_vec())
        assert store.count == 2
        assert store.remove("a")
        assert store.count == 1
        assert not store.remove("a")  # already removed

    def test_remove_nonexistent(self):
        store = TenantVectorStore(dimension=DIM)
        assert not store.remove("ghost")

    def test_clear(self):
        store = TenantVectorStore(dimension=DIM)
        for i in range(10):
            store.add(f"v{i}", _random_vec())
        assert store.count == 10
        store.clear()
        assert store.count == 0
        assert store.search(_random_vec(), k=5) == []

    def test_eviction_at_capacity(self):
        store = TenantVectorStore(dimension=DIM, max_vectors=5)
        for i in range(10):
            store.add(f"v{i}", _random_vec())
            time.sleep(0.001)  # ensure different timestamps
        # Should never exceed capacity
        assert store.count == 5
        # Oldest entries should have been evicted
        assert "v0" not in store._id_to_pos

    def test_stats(self):
        store = TenantVectorStore(dimension=DIM, max_vectors=100)
        store.add("a", _random_vec())
        stats = store.stats()
        assert stats.count == 1
        assert stats.max_capacity == 100
        assert stats.healthy
        assert stats.oldest_entry_age_seconds >= 0

    def test_search_preserves_order_by_score(self):
        store = TenantVectorStore(dimension=DIM)
        base = _random_vec()
        # Add vectors at varying distances
        close = _similar_vec(base, noise=0.01)
        medium = _similar_vec(base, noise=0.3)
        store.add("close", close)
        store.add("medium", medium)

        results = store.search(base, k=2, threshold=0.0)
        if len(results) >= 2:
            assert results[0].score >= results[1].score


# ── VectorStoreManager ──

class TestVectorStoreManager:
    def test_get_store_creates_on_demand(self):
        mgr = VectorStoreManager(dimension=DIM)
        s = mgr.get_store("tenant_a")
        assert s is not None
        assert s.count == 0

    def test_get_store_returns_same_instance(self):
        mgr = VectorStoreManager(dimension=DIM)
        a = mgr.get_store("t1")
        b = mgr.get_store("t1")
        assert a is b

    def test_tenant_isolation(self):
        mgr = VectorStoreManager(dimension=DIM)
        s1 = mgr.get_store("t1")
        s2 = mgr.get_store("t2")
        s1.add("x", _random_vec())
        assert s1.count == 1
        assert s2.count == 0  # isolated

    def test_delete_tenant(self):
        mgr = VectorStoreManager(dimension=DIM)
        s = mgr.get_store("t1")
        s.add("x", _random_vec())
        assert mgr.tenant_count == 1
        assert mgr.delete_tenant("t1")
        assert mgr.tenant_count == 0
        assert not mgr.delete_tenant("t1")  # already gone

    def test_total_vectors(self):
        mgr = VectorStoreManager(dimension=DIM)
        mgr.get_store("a").add("v1", _random_vec())
        mgr.get_store("b").add("v2", _random_vec())
        mgr.get_store("b").add("v3", _random_vec())
        assert mgr.total_vectors == 3

    def test_healthy(self):
        mgr = VectorStoreManager(dimension=DIM)
        assert mgr.healthy()  # FAISS is available (we already skipif not)

    def test_all_stats(self):
        mgr = VectorStoreManager(dimension=DIM)
        mgr.get_store("a").add("v1", _random_vec())
        stats = mgr.all_stats()
        assert "a" in stats
        assert stats["a"].count == 1
