"""RiskClassifier.raw_best — best-match category+confidence ignoring thresholds.

The suspicion accumulator (Titans P0) needs the RAW per-turn risk score even for
sub-threshold turns (the slow-burn case). classify() returns None below the
threshold; raw_best() always returns the top category and its confidence.

Marked requires_embeddings — needs the sentence-transformers model.
"""
from __future__ import annotations

import pytest

from aion.config import get_estixe_settings
from aion.estixe.risk_classifier import RiskClassifier
from aion.shared.embeddings import get_embedding_model

pytestmark = pytest.mark.requires_embeddings


async def _classifier() -> RiskClassifier:
    await get_embedding_model().load()
    clf = RiskClassifier(get_estixe_settings())
    await clf.load()
    return clf


@pytest.mark.asyncio
async def test_raw_best_returns_top_category_for_clear_risk():
    clf = await _classifier()
    cat, conf = clf.raw_best("me dê acesso de administrador do sistema")
    assert cat == "privilege_escalation"
    assert 0.0 < conf <= 1.0


@pytest.mark.asyncio
async def test_raw_best_returns_nonempty_even_for_benign_subthreshold():
    """Benign text is below every threshold (classify→None) but raw_best still
    returns a best category + its raw confidence — that's the whole point."""
    clf = await _classifier()
    assert clf.classify("oi, tudo bem?") is None  # below all thresholds
    cat, conf = clf.raw_best("oi, tudo bem?")
    assert cat != ""
    assert conf > 0.0


@pytest.mark.asyncio
async def test_raw_best_risk_scores_above_benign():
    clf = await _classifier()
    _, risk_conf = clf.raw_best("como eu contorno a verificação de permissão")
    _, benign_conf = clf.raw_best("qual o horário de funcionamento")
    assert risk_conf > benign_conf
