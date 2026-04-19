"""Tests for the auto-discovery suggestion engine."""

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from aion.estixe.suggestions import (
    PassthroughSample,
    SuggestionEngine,
    get_suggestion_engine,
)


def _make_embedding(seed: int, dim: int = 8) -> np.ndarray:
    """Deterministic normalized embedding from seed."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _make_sample(
    seed: int,
    *,
    text: str = "test query",
    tenant: str = "t1",
    cost: float = 0.01,
    resp_len: int = 100,
    timestamp: float | None = None,
) -> PassthroughSample:
    return PassthroughSample(
        timestamp=timestamp if timestamp is not None else time.time(),
        user_message=text,
        embedding=_make_embedding(seed),
        response_length=resp_len,
        cost=cost,
        tenant=tenant,
    )


class TestGreedyClustering:
    def test_empty_samples_return_no_clusters(self):
        engine = SuggestionEngine()
        clusters = engine._greedy_cluster([])
        assert clusters == []

    def test_single_sample_one_cluster(self):
        engine = SuggestionEngine()
        clusters = engine._greedy_cluster([_make_sample(1)])
        assert len(clusters) == 1
        assert len(clusters[0]) == 1

    def test_similar_embeddings_cluster_together(self):
        engine = SuggestionEngine(similarity_threshold=0.8)
        base = _make_embedding(42)
        # Create samples with very small noise — should cluster
        samples = []
        for i in range(5):
            s = _make_sample(100 + i)
            noise = np.random.default_rng(i).standard_normal(8).astype(np.float32) * 0.05
            s.embedding = (base + noise) / np.linalg.norm(base + noise)
            samples.append(s)

        clusters = engine._greedy_cluster(samples)
        # All should be in one cluster
        assert len(clusters) == 1
        assert len(clusters[0]) == 5

    def test_different_embeddings_separate_clusters(self):
        engine = SuggestionEngine(similarity_threshold=0.85)
        # 3 very different random embeddings
        samples = [_make_sample(i * 1000) for i in range(3)]
        clusters = engine._greedy_cluster(samples)
        # Likely 3 separate clusters (low chance random vectors are >0.85 similar)
        assert len(clusters) >= 2


class TestSuggestionGeneration:
    def test_no_suggestions_below_min_cluster_size(self):
        engine = SuggestionEngine(min_cluster_size=3)
        state = engine._get_state("t1")
        # Add only 2 samples
        state.samples.append(_make_sample(1))
        state.samples.append(_make_sample(2))
        assert engine.generate("t1") == []

    def test_cluster_above_min_generates_suggestion(self):
        engine = SuggestionEngine(similarity_threshold=0.5, min_cluster_size=3)
        state = engine._get_state("t1")
        base = _make_embedding(7)
        for i in range(4):
            s = _make_sample(100 + i, text=f"message variant {i}")
            s.embedding = base + np.random.default_rng(i).standard_normal(8).astype(np.float32) * 0.01
            s.embedding = s.embedding / np.linalg.norm(s.embedding)
            state.samples.append(s)

        suggestions = engine.generate("t1")
        assert len(suggestions) == 1
        assert suggestions[0].cluster_size == 4

    def test_rejected_suggestion_filtered_out(self):
        engine = SuggestionEngine(similarity_threshold=0.5, min_cluster_size=3)
        state = engine._get_state("t1")
        base = _make_embedding(9)
        for i in range(4):
            s = _make_sample(100 + i)
            s.embedding = base.copy()
            state.samples.append(s)

        sugs = engine.generate("t1")
        assert len(sugs) == 1
        sug_id = sugs[0].id

        engine.reject("t1", sug_id)
        assert engine.generate("t1") == []

    def test_approved_suggestion_filtered_out(self):
        engine = SuggestionEngine(similarity_threshold=0.5, min_cluster_size=3)
        state = engine._get_state("t1")
        base = _make_embedding(11)
        for i in range(4):
            s = _make_sample(100 + i)
            s.embedding = base.copy()
            state.samples.append(s)

        sugs = engine.generate("t1")
        sug_id = sugs[0].id
        assert engine.approve("t1", sug_id)
        assert engine.generate("t1") == []

    def test_approve_returns_false_for_unknown_id(self):
        engine = SuggestionEngine()
        assert not engine.approve("t1", "nonexistent")

    def test_tenant_isolation(self):
        engine = SuggestionEngine(similarity_threshold=0.5, min_cluster_size=3)

        base1 = _make_embedding(20)
        for i in range(4):
            s = _make_sample(200 + i, tenant="tenant_a")
            s.embedding = base1.copy()
            engine._get_state("tenant_a").samples.append(s)

        # Tenant B has no samples
        assert engine.generate("tenant_a") != []
        assert engine.generate("tenant_b") == []

    def test_delete_tenant_clears_state(self):
        engine = SuggestionEngine()
        engine._get_state("doomed").samples.append(_make_sample(1))
        engine.delete_tenant("doomed")
        assert engine.tenant_sample_count("doomed") == 0


class TestIntentNameSuggestion:
    def test_extracts_common_meaningful_word(self):
        engine = SuggestionEngine()
        name = engine._suggest_intent_name([
            "Qual o horario de funcionamento?",
            "Qual o horario?",
            "Preciso do horario de atendimento",
        ])
        assert "horario" in name

    def test_filters_stopwords(self):
        engine = SuggestionEngine()
        name = engine._suggest_intent_name([
            "me diz qual",
            "qual de me",
            "de qual me",
        ])
        # Should not return stopword-based name
        assert name != "intent_"

    def test_empty_input_returns_fallback(self):
        engine = SuggestionEngine()
        name = engine._suggest_intent_name([""])
        assert name == "novo_intent"


class TestClusterId:
    def test_same_centroid_same_id(self):
        engine = SuggestionEngine()
        c = _make_embedding(1)
        id1 = engine._cluster_id(c)
        id2 = engine._cluster_id(c)
        assert id1 == id2

    def test_different_centroids_different_ids(self):
        engine = SuggestionEngine()
        id1 = engine._cluster_id(_make_embedding(1))
        id2 = engine._cluster_id(_make_embedding(2))
        assert id1 != id2


class TestConfidenceAndSavings:
    def test_confidence_is_between_zero_and_one(self):
        engine = SuggestionEngine(similarity_threshold=0.5, min_cluster_size=3)
        state = engine._get_state("t1")
        base = _make_embedding(30)
        for i in range(4):
            s = _make_sample(300 + i)
            s.embedding = base.copy()
            state.samples.append(s)

        sugs = engine.generate("t1")
        assert 0 <= sugs[0].confidence <= 1.0

    def test_savings_scales_with_cluster_size(self):
        engine = SuggestionEngine(similarity_threshold=0.5, min_cluster_size=3)
        state = engine._get_state("t1")
        base = _make_embedding(40)
        now = time.time()
        # Cluster of 10 samples over a minute — high daily projection
        for i in range(10):
            s = _make_sample(400 + i, cost=0.01, timestamp=now - 60 + i)
            s.embedding = base.copy()
            state.samples.append(s)

        sugs = engine.generate("t1")
        # 10 samples in 1 min → 14400 per day → 14400 * 0.01 = 144
        assert sugs[0].estimated_daily_savings > 50


class TestRecord:
    def test_record_disabled_when_model_not_loaded(self):
        engine = SuggestionEngine()
        with patch("aion.shared.embeddings.get_embedding_model") as mock:
            mock_instance = MagicMock()
            mock_instance.loaded = False
            mock.return_value = mock_instance
            engine.record("t1", "test message", response_length=100, cost=0.01)
        assert engine.tenant_sample_count("t1") == 0

    def test_record_skips_empty_after_sanitize(self):
        engine = SuggestionEngine()
        # Will try to encode but _sanitize returns empty → skip
        with patch.object(engine, "_sanitize", return_value=""):
            engine.record("t1", "some text", response_length=50, cost=0.01)
        assert engine.tenant_sample_count("t1") == 0

    def test_record_never_raises_on_failure(self):
        engine = SuggestionEngine()
        # Force exception in encode
        with patch("aion.shared.embeddings.get_embedding_model", side_effect=Exception("boom")):
            engine.record("t1", "test", response_length=10, cost=0.001)
        # No exception propagated


class TestSingleton:
    def test_get_suggestion_engine_returns_same_instance(self):
        import aion.estixe.suggestions as mod
        mod._instance = None
        try:
            a = get_suggestion_engine()
            b = get_suggestion_engine()
            assert a is b
        finally:
            mod._instance = None
