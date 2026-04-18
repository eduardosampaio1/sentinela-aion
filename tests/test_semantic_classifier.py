"""Tests for the hybrid semantic + heuristic complexity classifier."""

import pytest

from aion.nomos.classifier import ComplexityClassifier, ComplexityResult


@pytest.fixture
def classifier():
    """Classifier with heuristic only (no archetypes loaded)."""
    return ComplexityClassifier()


class TestHeuristicFallback:
    """When semantic is unavailable, heuristic should work exactly as v1."""

    def test_simple_greeting(self, classifier):
        result = classifier.classify([{"role": "user", "content": "oi"}])
        assert result.score < 30
        assert result.method == "heuristic"

    def test_code_request(self, classifier):
        result = classifier.classify([
            {"role": "user", "content": "implement a binary search function in Python"}
        ])
        assert result.score > 10  # code + implement patterns
        assert result.method == "heuristic"

    def test_complex_multi_pattern(self, classifier):
        result = classifier.classify([
            {"role": "user", "content": "explain step by step how to implement and debug an algorithm"}
        ])
        assert result.score > 20

    def test_no_user_message(self, classifier):
        result = classifier.classify([{"role": "system", "content": "you are helpful"}])
        assert result.score == 0

    def test_empty_messages(self, classifier):
        result = classifier.classify([])
        assert result.score == 0

    def test_yes_is_simple(self, classifier):
        result = classifier.classify([{"role": "user", "content": "yes"}])
        assert result.score < 10

    def test_long_conversation(self, classifier):
        msgs = [{"role": "user", "content": "hi"}] * 12
        result = classifier.classify(msgs)
        assert "long_conversation" in str(result.factors)


@pytest.mark.slow
class TestHybridClassifier:
    """Tests with real embeddings — semantic + heuristic."""

    @pytest.fixture(autouse=True)
    async def _load_archetypes(self):
        from pathlib import Path
        c = ComplexityClassifier()
        config_dir = Path(__file__).parent.parent / "config"
        await c.load_archetypes(config_dir)
        self.classifier = c

    def test_hybrid_method(self):
        result = self.classifier.classify([{"role": "user", "content": "oi"}])
        assert result.method == "hybrid"
        assert result.semantic_score is not None
        assert result.heuristic_score is not None

    def test_simple_scores_low(self):
        result = self.classifier.classify([{"role": "user", "content": "obrigado"}])
        assert result.score < 40

    def test_complex_scores_high(self):
        result = self.classifier.classify([
            {"role": "user", "content": "implement a distributed lock with Redis using Redlock algorithm with retry and fencing tokens"}
        ])
        assert result.score > 40

    def test_moderate_in_between(self):
        result = self.classifier.classify([
            {"role": "user", "content": "explain what machine learning is"}
        ])
        assert 15 < result.score < 75

    def test_semantic_score_varies_by_complexity(self):
        simple = self.classifier.classify([{"role": "user", "content": "thanks"}])
        expert = self.classifier.classify([
            {"role": "user", "content": "design a multi-region disaster recovery strategy for financial services"}
        ])
        assert simple.semantic_score < expert.semantic_score
