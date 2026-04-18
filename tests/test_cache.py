"""Tests for the semantic cache module."""

import time
from unittest.mock import patch

import numpy as np
import pytest

from aion.shared.vector_store import _FAISS_AVAILABLE

pytestmark = pytest.mark.skipif(not _FAISS_AVAILABLE, reason="faiss-cpu not installed")


def _make_request(content: str = "test question", model: str = "gpt-4o-mini"):
    from aion.shared.schemas import ChatCompletionRequest, ChatMessage
    return ChatCompletionRequest(
        model=model,
        messages=[ChatMessage(role="user", content=content)],
    )


def _make_response(content: str = "test answer", model: str = "gpt-4o-mini"):
    from aion.shared.schemas import (
        ChatCompletionChoice,
        ChatCompletionResponse,
        ChatMessage,
        UsageInfo,
    )
    return ChatCompletionResponse(
        model=model,
        choices=[ChatCompletionChoice(
            index=0,
            message=ChatMessage(role="assistant", content=content),
            finish_reason="stop",
        )],
        usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


def _make_context(tenant: str = "test_tenant"):
    from aion.shared.schemas import PipelineContext
    return PipelineContext(tenant=tenant)


@pytest.fixture
def cache():
    """Fresh SemanticCache with cache enabled."""
    from aion.cache import SemanticCache
    with patch("aion.cache.get_cache_settings") as mock_settings:
        mock_settings.return_value.enabled = True
        mock_settings.return_value.similarity_threshold = 0.90
        mock_settings.return_value.default_ttl_seconds = 3600
        mock_settings.return_value.ttl_factual = 86400
        mock_settings.return_value.ttl_creative = 3600
        mock_settings.return_value.ttl_code = 7200
        mock_settings.return_value.followup_threshold = 2
        c = SemanticCache()
        c._settings = mock_settings.return_value
        yield c


class TestCacheDisabled:
    def test_lookup_returns_none_when_disabled(self):
        from aion.cache import SemanticCache
        with patch("aion.cache.get_cache_settings") as mock:
            mock.return_value.enabled = False
            c = SemanticCache()
            c._settings = mock.return_value
            result = c.lookup(_make_request(), _make_context())
            assert result is None

    def test_store_does_nothing_when_disabled(self):
        from aion.cache import SemanticCache
        with patch("aion.cache.get_cache_settings") as mock:
            mock.return_value.enabled = False
            c = SemanticCache()
            c._settings = mock.return_value
            c.store(_make_request(), _make_response(), _make_context())
            # no error, no crash


@pytest.mark.slow
class TestCacheStoreAndLookup:
    @pytest.fixture(autouse=True)
    async def _load_model(self):
        from aion.shared.embeddings import get_embedding_model
        model = get_embedding_model()
        if not model.loaded:
            await model.load()

    def test_store_and_hit(self, cache):
        req = _make_request("Qual e a capital do Brasil?")
        resp = _make_response("A capital do Brasil e Brasilia.")
        ctx = _make_context()

        cache.store(req, resp, ctx)

        # Same question — should hit
        result = cache.lookup(req, ctx)
        assert result is not None
        assert "Brasilia" in result.choices[0].message.content
        assert cache.stats.hits == 1

    def test_similar_question_hits(self, cache):
        req1 = _make_request("Qual e a capital do Brasil?")
        resp = _make_response("A capital do Brasil e Brasilia.")
        ctx = _make_context()

        cache.store(req1, resp, ctx)

        # Very close rephrase (similarity ~0.95 with MiniLM)
        req2 = _make_request("Qual a capital do Brasil")
        result = cache.lookup(req2, ctx)
        assert result is not None
        assert cache.stats.hits >= 1

    def test_different_question_misses(self, cache):
        req1 = _make_request("Qual e a capital do Brasil?")
        resp = _make_response("A capital do Brasil e Brasilia.")
        ctx = _make_context()

        cache.store(req1, resp, ctx)

        # Completely different question
        req2 = _make_request("Implementa um quicksort em Rust")
        result = cache.lookup(req2, ctx)
        assert result is None
        assert cache.stats.misses >= 1

    def test_tenant_isolation(self, cache):
        req = _make_request("Qual e a capital do Brasil?")
        resp = _make_response("Brasilia")
        ctx1 = _make_context("tenant_a")
        ctx2 = _make_context("tenant_b")

        cache.store(req, resp, ctx1)

        # Same question, different tenant — should miss
        result = cache.lookup(req, ctx2)
        assert result is None

    def test_ttl_expiration(self, cache):
        req = _make_request("test question")
        resp = _make_response("test answer")
        ctx = _make_context()

        cache.store(req, resp, ctx)

        # Manually expire the entry
        from aion.shared.vector_store import get_vector_store_manager
        from aion.shared.embeddings import get_embedding_model
        mgr = get_vector_store_manager(dimension=get_embedding_model().dimension)
        store = mgr.get_store("cache:test_tenant")
        for entry in store._entries:
            entry["metadata"]["cached_at"] = time.time() - 999999  # expired long ago

        result = cache.lookup(req, ctx)
        assert result is None

    def test_delete_tenant(self, cache):
        req = _make_request("test")
        resp = _make_response("answer")
        ctx = _make_context("doomed_tenant")

        cache.store(req, resp, ctx)
        cache.delete_tenant("doomed_tenant")

        result = cache.lookup(req, ctx)
        assert result is None


@pytest.mark.slow
class TestCacheInvalidation:
    @pytest.fixture(autouse=True)
    async def _load_model(self):
        from aion.shared.embeddings import get_embedding_model
        model = get_embedding_model()
        if not model.loaded:
            await model.load()

    def test_single_followup_does_not_invalidate(self, cache):
        """Single followup signal alone should NOT invalidate (multi-signal)."""
        cache.record_followup("t1", "entry_123", followup_similarity=0.5)
        # entry still tracked but not invalidated (threshold is 2)
        assert cache._stats.invalidations == 0

    def test_double_followup_invalidates(self, cache):
        """Two followups on same entry should invalidate."""
        cache.record_followup("t1", "entry_456", followup_similarity=0.5)
        cache.record_followup("t1", "entry_456", followup_similarity=0.5)
        assert cache._stats.invalidations == 1

    def test_followup_plus_low_similarity_invalidates(self, cache):
        """Followup + low similarity = combined signal → invalidate."""
        cache.record_followup("t1", "entry_789", followup_similarity=0.1)  # low similarity
        # First followup with low similarity → should invalidate
        # Actually, count=1 and low_similarity=True → combined signal triggers invalidation
        assert cache._stats.invalidations == 1


class TestCacheStats:
    def test_initial_stats(self):
        from aion.cache import SemanticCache
        with patch("aion.cache.get_cache_settings") as mock:
            mock.return_value.enabled = True
            mock.return_value.followup_threshold = 2
            c = SemanticCache()
            c._settings = mock.return_value
            assert c.stats.hits == 0
            assert c.stats.misses == 0
            assert c.stats.hit_rate == 0.0
