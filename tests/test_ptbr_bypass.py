"""PT-BR bypass regression tests (ESTIXE SemanticClassifier).

Track: estixe-multilingual-ptbr.

The bypass (0-token canned reply for greetings/confirmations) is gated by
`bypass_threshold` against intents.yaml. Swapping the shared embedding to
paraphrase-multilingual-MiniLM-L12-v2 shifted the cosine-similarity
distribution, so the old 0.85 threshold dropped greeting recall — e.g.
"oi, tudo bem?" scored ~0.82 and leaked to passthrough (an avoidable LLM call,
breaking the cost-control promise). bypass_threshold was recalibrated to 0.74.

These tests guard greeting recall WITHOUT false-bypassing real questions, using
the shipped intents.yaml + the production default threshold.
Skippable in lean CI with `-m "not requires_embeddings"`.
"""
import asyncio

import pytest

from aion.config import EstixeSettings
from aion.estixe.classifier import SemanticClassifier

pytestmark = pytest.mark.requires_embeddings


@pytest.fixture
def clf():
    # EstixeSettings() = shipped intents_path + production default bypass_threshold (0.74).
    c = SemanticClassifier(EstixeSettings())
    asyncio.run(c.load())
    return c


# ── Greetings/confirmations MUST bypass (0-token reply) ─────────────────────
@pytest.mark.slow
@pytest.mark.parametrize("text", [
    "oi, tudo bem?",          # the reported regression
    "olá tudo bem?",
    "bom dia!",
    "opa, tudo certo?",
    "como você está?",
    "obrigado pela ajuda!",
    "tchau",
    "ok, entendi",
])
def test_greetings_bypass(clf, text):
    m = clf.classify(text)
    assert m is not None and m.action == "bypass", (
        f"{text!r} should bypass (got {None if m is None else (m.intent, round(m.confidence, 3))})"
    )


# ── Real questions must NOT be bypassed (no canned greeting to a real ask) ──
@pytest.mark.slow
@pytest.mark.parametrize("text", [
    "o que é CLT?",
    "quais os principais descontos na folha de pagamento?",
    "como funciona o FGTS?",
    "qual é o meu saldo atual?",
    "preciso de ajuda com a folha de ponto",
])
def test_real_questions_not_bypassed(clf, text):
    m = clf.classify(text)
    bypassed = m is not None and m.action == "bypass"
    detail = "no match" if m is None else f"intent={m.intent} conf={m.confidence:.3f}"
    assert not bypassed, f"{text!r} false-bypass ({detail})"
