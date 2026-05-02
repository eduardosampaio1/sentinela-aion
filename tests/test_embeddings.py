"""Tests for the shared embedding model singleton."""

import pytest
import numpy as np

from aion.shared.embeddings import EmbeddingModel, get_embedding_model

# P1.B: tests in this file that use the `loaded_model` fixture pull the real
# sentence-transformers/all-MiniLM-L6-v2 model from disk or HuggingFace.
# Lean CI environments may skip with `pytest -m "not requires_embeddings"`.
# Tests that don't load the model (e.g. test_model_not_loaded_by_default) keep
# running unconditionally — the marker is applied per-test below, not file-wide.


@pytest.fixture
def fresh_model():
    """A fresh (not yet loaded) embedding model instance."""
    return EmbeddingModel()


@pytest.fixture
async def loaded_model():
    """A loaded embedding model instance (uses real model — slow)."""
    model = EmbeddingModel()
    await model.load()
    return model


def test_model_not_loaded_by_default(fresh_model):
    assert not fresh_model.loaded
    assert fresh_model.dimension == 0
    assert fresh_model.model_name == ""


def test_encode_before_load_raises(fresh_model):
    with pytest.raises(RuntimeError, match="not loaded"):
        fresh_model.encode(["test"])


def test_encode_single_before_load_raises(fresh_model):
    with pytest.raises(RuntimeError, match="not loaded"):
        fresh_model.encode_single("test")


@pytest.mark.slow
@pytest.mark.requires_embeddings
@pytest.mark.asyncio
async def test_load_model(fresh_model):
    await fresh_model.load()
    assert fresh_model.loaded
    assert fresh_model.dimension == 384  # MiniLM-L6-v2
    assert "MiniLM" in fresh_model.model_name


@pytest.mark.slow
@pytest.mark.requires_embeddings
@pytest.mark.asyncio
async def test_load_is_idempotent(fresh_model):
    await fresh_model.load()
    await fresh_model.load()  # should not fail
    assert fresh_model.loaded


@pytest.mark.slow
@pytest.mark.requires_embeddings
@pytest.mark.asyncio
async def test_encode_batch(loaded_model):
    result = loaded_model.encode(["hello", "world"])
    assert isinstance(result, np.ndarray)
    assert result.shape == (2, 384)


@pytest.mark.slow
@pytest.mark.requires_embeddings
@pytest.mark.asyncio
async def test_encode_single_returns_vector(loaded_model):
    result = loaded_model.encode_single("hello world")
    assert isinstance(result, np.ndarray)
    assert result.shape == (384,)


@pytest.mark.slow
@pytest.mark.requires_embeddings
@pytest.mark.asyncio
async def test_encode_single_cached(loaded_model):
    v1 = loaded_model.encode_single("test query")
    v2 = loaded_model.encode_single("test query")
    np.testing.assert_array_equal(v1, v2)


@pytest.mark.slow
@pytest.mark.requires_embeddings
@pytest.mark.asyncio
async def test_encode_single_cache_disabled(loaded_model):
    v1 = loaded_model.encode_single("test", use_cache=False)
    v2 = loaded_model.encode_single("test", use_cache=False)
    np.testing.assert_array_almost_equal(v1, v2)


@pytest.mark.slow
@pytest.mark.requires_embeddings
@pytest.mark.asyncio
async def test_clear_cache(loaded_model):
    loaded_model.encode_single("cached text")
    assert len(loaded_model._cache) > 0
    loaded_model.clear_cache()
    assert len(loaded_model._cache) == 0


@pytest.mark.slow
@pytest.mark.requires_embeddings
@pytest.mark.asyncio
async def test_normalized_embeddings(loaded_model):
    """Normalized embeddings should have unit norm."""
    vec = loaded_model.encode_single("hello")
    norm = np.linalg.norm(vec)
    assert abs(norm - 1.0) < 0.01


@pytest.mark.slow
@pytest.mark.requires_embeddings
@pytest.mark.asyncio
async def test_similar_texts_high_similarity(loaded_model):
    """Semantically similar texts should have high cosine similarity."""
    v1 = loaded_model.encode_single("good morning")
    v2 = loaded_model.encode_single("hello, good day")
    similarity = float(v1 @ v2)
    assert similarity > 0.5


@pytest.mark.slow
@pytest.mark.requires_embeddings
@pytest.mark.asyncio
async def test_dissimilar_texts_low_similarity(loaded_model):
    """Semantically different texts should have lower similarity."""
    v1 = loaded_model.encode_single("good morning")
    v2 = loaded_model.encode_single("implement binary search in rust")
    similarity = float(v1 @ v2)
    assert similarity < 0.5


def test_singleton_returns_same_instance():
    """get_embedding_model() should return the same instance."""
    import aion.shared.embeddings as mod
    old = mod._instance
    mod._instance = None  # reset
    try:
        a = get_embedding_model()
        b = get_embedding_model()
        assert a is b
    finally:
        mod._instance = old
