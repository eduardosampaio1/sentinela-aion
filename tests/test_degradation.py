"""Tests for graceful degradation when sentence-transformers is unavailable.

Verifies that:
1. ESTIXE initializes successfully (PII + policy still work)
2. Bypass is disabled but block and PII detection still function
3. Pipeline doesn't 503 — falls through to CALL_LLM
4. NOMOS falls back to heuristic classifier
5. Cache returns miss (not error)
"""

import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from aion.shared.schemas import (
    ChatCompletionRequest,
    ChatMessage,
    Decision,
    PipelineContext,
)


def _make_request(content: str = "test") -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content=content)],
    )


def _make_context(tenant: str = "test") -> PipelineContext:
    return PipelineContext(tenant=tenant)


class TestEmbeddingModelDegradation:
    """Test EmbeddingModel behavior when sentence-transformers is missing."""

    @pytest.mark.asyncio
    async def test_load_does_not_raise_on_import_error(self):
        """EmbeddingModel.load() should silently degrade, not raise."""
        from aion.shared.embeddings import EmbeddingModel
        m = EmbeddingModel()
        # Simulate sentence_transformers not being importable
        # by patching the import inside load() only
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def fake_import(name, *args, **kwargs):
            if name == "sentence_transformers":
                raise ImportError("No module named 'sentence_transformers'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            await m.load()  # should NOT raise
        assert not m.loaded
        assert m._load_failed

    @pytest.mark.asyncio
    async def test_load_idempotent_after_failure(self):
        from aion.shared.embeddings import EmbeddingModel
        m = EmbeddingModel()
        m._load_failed = True
        await m.load()  # should be no-op
        assert not m.loaded

    def test_dimension_zero_when_not_loaded(self):
        from aion.shared.embeddings import EmbeddingModel
        m = EmbeddingModel()
        assert m.dimension == 0


class TestEstixeDegradation:
    """Test ESTIXE when embedding model is unavailable."""

    @pytest.mark.asyncio
    async def test_initialize_succeeds_without_embeddings(self, tmp_path):
        """ESTIXE should initialize even if classifier can't load embeddings."""
        from aion.config import EstixeSettings
        from aion.estixe import EstixeModule

        # Create minimal intents + policies
        intents = tmp_path / "intents.yaml"
        intents.write_text("intents: {}", encoding="utf-8")

        with patch("aion.estixe.classifier.get_embedding_model") as mock_model:
            mock_instance = MagicMock()
            mock_instance.loaded = False
            # Python 3.11 removed asyncio.coroutine — use AsyncMock instead.
            mock_instance.load = AsyncMock(return_value=None)
            mock_model.return_value = mock_instance

            with patch("aion.config.get_estixe_settings") as mock_settings:
                mock_settings.return_value = EstixeSettings(
                    intents_path=intents,
                    bypass_threshold=0.85,
                )
                module = EstixeModule()
                await module.initialize()

        assert module._initialized

    @pytest.mark.asyncio
    async def test_pii_still_works_without_embeddings(self):
        """PII detection (regex) should work even without embedding model."""
        from aion.estixe.guardrails import Guardrails

        g = Guardrails()
        result = g.check_output("meu CPF e 123.456.789-00")
        assert not result.safe
        assert any("cpf" in v for v in result.violations)

    @pytest.mark.asyncio
    async def test_policy_still_works_without_embeddings(self, tmp_path):
        """Policy engine (regex/keywords) should work without embedding model."""
        from aion.estixe.policy import PolicyEngine

        policies = tmp_path / "policies.yaml"
        policies.write_text("""
policies:
  - name: block_test
    action: block
    keywords:
      - "blocked_keyword"
""", encoding="utf-8")

        engine = PolicyEngine()
        await engine.load(policies)
        ctx = _make_context()
        result = await engine.check("this has blocked_keyword in it", ctx)
        assert result.blocked


class TestNomosDegradation:
    """Test NOMOS classifier falls back to heuristic."""

    def test_heuristic_fallback_without_archetypes(self):
        from aion.nomos.classifier import ComplexityClassifier
        c = ComplexityClassifier()
        # No archetypes loaded — semantic_ready = False
        result = c.classify([{"role": "user", "content": "implement quicksort"}])
        assert result.method == "heuristic"
        assert result.semantic_score is None
        assert result.score > 0  # heuristic still scored it

    @pytest.mark.asyncio
    async def test_load_archetypes_degrades_without_model(self, tmp_path):
        from aion.nomos.classifier import ComplexityClassifier

        # Create archetypes file
        archetypes = tmp_path / "complexity_archetypes.yaml"
        archetypes.write_text("""
tiers:
  simple:
    score_range: [0, 25]
    examples: ["oi", "hello"]
""", encoding="utf-8")

        mock_instance = MagicMock()
        mock_instance.loaded = False

        async def fake_load():
            pass
        mock_instance.load = fake_load

        with patch("aion.shared.embeddings.get_embedding_model", return_value=mock_instance):
            c = ComplexityClassifier()
            await c.load_archetypes(tmp_path)

        # Should fall back to heuristic
        assert not c._semantic_ready
        result = c.classify([{"role": "user", "content": "oi"}])
        assert result.method == "heuristic"


class TestCacheDegradation:
    """Test cache behavior without embedding model."""

    def test_cache_lookup_returns_none_without_model(self):
        from aion.cache import SemanticCache
        with patch("aion.cache.get_cache_settings") as mock:
            mock.return_value.enabled = True
            mock.return_value.similarity_threshold = 0.92
            mock.return_value.default_ttl_seconds = 3600
            mock.return_value.followup_threshold = 2
            c = SemanticCache()
            c._settings = mock.return_value

        with patch("aion.cache.get_embedding_model") as mock_model:
            mock_model.return_value.loaded = False
            result = c.lookup(_make_request("test"), _make_context())

        assert result is None  # miss, not error


class TestPipelineDegradation:
    """Test full pipeline behavior when ESTIXE can't load embeddings."""

    @pytest.mark.asyncio
    async def test_pipeline_does_not_503(self):
        """Pipeline should continue (CALL_LLM) when ESTIXE partially degrades."""
        from aion.pipeline import Pipeline

        # Create a mock ESTIXE that initializes but has no classifier
        class DegradedEstixe:
            name = "estixe"
            async def process(self, request, context):
                # Simulates ESTIXE without classifier: PII works, bypass doesn't
                # Decision stays CONTINUE (no bypass)
                return context

        pipeline = Pipeline()
        pipeline.register_pre(DegradedEstixe())

        ctx = _make_context()
        ctx = await pipeline.run_pre(_make_request("hello"), ctx)

        # Should be CONTINUE (not 503, not error)
        assert ctx.decision == Decision.CONTINUE
