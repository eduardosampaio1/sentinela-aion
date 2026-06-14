"""ACCUMULATED_PRESSURE — the Titans P0 pattern.

Fires from the persisted suspicion scalar (surprise + momentum), so it catches
slow-burn probing whose per-turn risk is NOT strictly increasing — exactly the
case the legacy PROGRESSIVE_BYPASS (all-increasing) check misses.
"""
from __future__ import annotations

import time

import pytest
from unittest.mock import AsyncMock, patch

from aion.estixe.threat_detector import (
    ThreatDetector,
    ThreatPattern,
    ThreatStore,
    _analyze,
)
from aion.shared.turn_context import TurnSummary


def _t(risk: float = 0.1, intent: str = "", decision: str = "continue") -> TurnSummary:
    return TurnSummary(
        intent=intent, risk_score=risk, complexity=40.0,
        model_used="gpt-4o-mini", decision=decision, timestamp=time.time(),
    )


# Non-monotonic risks: opener ≥ 0.3 (no INTENT_MUTATION) and not strictly
# increasing (no PROGRESSIVE_BYPASS). Only the accumulator can flag this.
_NON_MONOTONIC = [_t(0.5), _t(0.3), _t(0.55), _t(0.4)]


def test_fires_on_high_suspicion_despite_non_monotonic_risk():
    sig = _analyze(_NON_MONOTONIC, suspicion=1.0, suspicion_detect_threshold=0.6)
    assert sig is not None
    assert sig.pattern == ThreatPattern.ACCUMULATED_PRESSURE


def test_not_fired_when_suspicion_below_threshold():
    sig = _analyze(_NON_MONOTONIC, suspicion=0.1, suspicion_detect_threshold=0.6)
    if sig is not None:
        assert sig.pattern != ThreatPattern.ACCUMULATED_PRESSURE


def test_recommends_block_session_at_very_high_suspicion():
    sig = _analyze(_NON_MONOTONIC, suspicion=2.0, suspicion_detect_threshold=0.6)
    assert sig is not None
    assert sig.pattern == ThreatPattern.ACCUMULATED_PRESSURE
    assert sig.recommended_action == "block_session"


def test_recommends_escalate_at_moderate_suspicion():
    sig = _analyze(_NON_MONOTONIC, suspicion=0.7, suspicion_detect_threshold=0.6)
    assert sig is not None
    assert sig.pattern == ThreatPattern.ACCUMULATED_PRESSURE
    assert sig.recommended_action == "escalate_threshold"


def test_confidence_scales_with_suspicion():
    low = _analyze(_NON_MONOTONIC, suspicion=0.7, suspicion_detect_threshold=0.6)
    high = _analyze(_NON_MONOTONIC, suspicion=2.5, suspicion_detect_threshold=0.6)
    assert high.confidence >= low.confidence


def test_backward_compatible_when_no_suspicion_passed():
    """Default suspicion=0.0 must never produce ACCUMULATED_PRESSURE — keeps the
    existing four-pattern behaviour (and all legacy tests) intact."""
    sig = _analyze(_NON_MONOTONIC)
    if sig is not None:
        assert sig.pattern != ThreatPattern.ACCUMULATED_PRESSURE


@pytest.mark.asyncio
async def test_detector_passes_suspicion_through():
    with patch.object(ThreatStore, "save", new_callable=AsyncMock):
        detector = ThreatDetector()
        sig = await detector.analyze("acme", "sess-burn", _NON_MONOTONIC, suspicion=1.5)
        assert sig is not None
        assert sig.pattern == ThreatPattern.ACCUMULATED_PRESSURE
        assert sig.session_id == "sess-burn"
        assert sig.tenant == "acme"
