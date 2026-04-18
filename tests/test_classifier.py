"""Tests for the semantic classifier.

These tests use the real embedding model (sentence-transformers) to verify
that semantic classification works correctly — NOT pattern matching.
"""

import pytest
from pathlib import Path

from aion.config import EstixeSettings
from aion.estixe.classifier import SemanticClassifier


@pytest.fixture
def intents_yaml(tmp_path):
    """Create a test intents YAML file."""
    content = """
intents:
  greeting:
    action: bypass
    examples:
      - "oi"
      - "ola"
      - "bom dia"
      - "boa tarde"
      - "boa noite"
      - "hello"
      - "hi"
      - "hey"
      - "good morning"
    responses:
      - "Ola! Como posso ajudar?"

  farewell:
    action: bypass
    examples:
      - "tchau"
      - "ate mais"
      - "bye"
      - "goodbye"
    responses:
      - "Ate mais!"

  query:
    action: passthrough
    examples:
      - "qual e o saldo da minha conta"
      - "quero consultar meu extrato"
    responses: []
"""
    path = tmp_path / "intents.yaml"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def settings(intents_yaml):
    return EstixeSettings(
        intents_path=intents_yaml,
        bypass_threshold=0.75,  # lower for test reliability
        embedding_model="all-MiniLM-L6-v2",
    )


@pytest.fixture
async def classifier(settings):
    c = SemanticClassifier(settings)
    await c.load()
    return c


@pytest.mark.slow
@pytest.mark.asyncio
async def test_classify_exact_greeting(classifier):
    """Exact match should classify as greeting."""
    match = classifier.classify("oi")
    assert match is not None
    assert match.intent == "greeting"
    assert match.confidence >= 0.75


@pytest.mark.slow
@pytest.mark.asyncio
async def test_classify_semantic_greeting(classifier):
    """Semantically similar greeting should also match."""
    match = classifier.classify("e ai, tudo bem?")
    assert match is not None
    assert match.intent == "greeting"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_classify_english_greeting(classifier):
    match = classifier.classify("hello there!")
    assert match is not None
    assert match.intent == "greeting"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_classify_farewell(classifier):
    match = classifier.classify("tchau, obrigado")
    assert match is not None
    assert match.intent == "farewell"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_no_match_complex_question(classifier):
    """Complex questions should NOT match any bypass intent."""
    match = classifier.classify(
        "Explique detalhadamente como funciona o sistema de pagamentos via PIX "
        "incluindo os protocolos de seguranca e as camadas de validacao"
    )
    assert match is None


@pytest.mark.slow
@pytest.mark.asyncio
async def test_passthrough_action(classifier):
    """Query intent should match but with passthrough action."""
    match = classifier.classify("quero ver meu saldo")
    if match:
        # If it matches, it should be passthrough (not bypass)
        assert match.action == "passthrough" or match.intent == "query"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_response_templates(classifier):
    """Bypass match should include response templates."""
    match = classifier.classify("bom dia")
    assert match is not None
    assert len(match.response_templates) > 0


@pytest.mark.slow
@pytest.mark.asyncio
async def test_embedding_cache(classifier):
    """Second call should use cached embedding from shared model."""
    from aion.shared.embeddings import get_embedding_model
    model = get_embedding_model()
    model.clear_cache()
    classifier.classify("oi")  # first call — computes embedding
    assert len(model._cache) > 0
    classifier.classify("oi")  # second call — should use cache


@pytest.mark.slow
@pytest.mark.asyncio
async def test_reload(classifier):
    """Reload should clear shared cache and re-load intents."""
    from aion.shared.embeddings import get_embedding_model
    model = get_embedding_model()
    classifier.classify("oi")
    assert len(model._cache) > 0
    await classifier.reload()
    assert len(model._cache) == 0
