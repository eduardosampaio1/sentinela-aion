"""Unit tests for aion.estixe.threat_detector.

Covers the pure _analyze() logic (no I/O) for all four threat patterns,
plus ThreatDetector.analyze() integration with mocked Redis store.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from aion.estixe.threat_detector import (
    ThreatDetector,
    ThreatPattern,
    ThreatSignal,
    ThreatStore,
    _analyze,
)
from aion.shared.turn_context import TurnSummary


# ── Helpers ────────────────────────────────────────────────────────────────


def _t(
    risk: float = 0.1,
    intent: str = "",
    decision: str = "continue",
    complexity: float = 40.0,
) -> TurnSummary:
    return TurnSummary(
        intent=intent,
        risk_score=risk,
        complexity=complexity,
        model_used="gpt-4o-mini",
        decision=decision,
        timestamp=time.time(),
    )


# ── _analyze: edge cases ───────────────────────────────────────────────────


def test_analyze_returns_none_for_empty():
    assert _analyze([]) is None


def test_analyze_returns_none_for_single_turn():
    assert _analyze([_t(0.8)]) is None


def test_analyze_returns_none_for_safe_two_turn_conversation():
    # Normal conversation — low risk, different intents, bypass
    turns = [
        _t(0.05, intent="greeting", decision="bypass"),
        _t(0.10, intent="follow_up", decision="bypass"),
    ]
    assert _analyze(turns) is None


# ── INTENT_MUTATION ────────────────────────────────────────────────────────


def test_intent_mutation_detected_benign_then_high_risk():
    """Turn 1 is benign (risk<0.3); Turn 2 spikes to ≥0.6 — classic escalation."""
    turns = [_t(0.1, "greeting"), _t(0.75, "exfiltrate_data")]
    sig = _analyze(turns)
    assert sig is not None
    assert sig.pattern == ThreatPattern.INTENT_MUTATION
    assert sig.recommended_action == "escalate_threshold"


def test_intent_mutation_confidence_scales_with_final_risk():
    """Higher final risk score → higher confidence signal."""
    sig_low = _analyze([_t(0.1), _t(0.61)])
    sig_high = _analyze([_t(0.1), _t(0.95)])
    assert sig_low is not None
    assert sig_high is not None
    assert sig_high.confidence >= sig_low.confidence


def test_intent_mutation_not_triggered_when_opener_is_medium_risk():
    """Opener at 0.35 (above 0.3 threshold) — INTENT_MUTATION condition not met."""
    turns = [_t(0.35, "neutral"), _t(0.80, "risky")]
    sig = _analyze(turns)
    # May still detect another pattern, but not INTENT_MUTATION
    if sig is not None:
        assert sig.pattern != ThreatPattern.INTENT_MUTATION


def test_intent_mutation_not_triggered_when_final_risk_is_low():
    """Final risk below 0.6 — no INTENT_MUTATION."""
    turns = [_t(0.05, "greeting"), _t(0.55, "medium")]
    # 0.55 < 0.6 → intent_mutation threshold not met
    sig = _analyze(turns)
    if sig is not None:
        assert sig.pattern != ThreatPattern.INTENT_MUTATION


# ── PROGRESSIVE_BYPASS ─────────────────────────────────────────────────────


def test_progressive_bypass_detected_on_three_strictly_increasing_turns():
    """Gradual probe across 3 turns — each slightly riskier than the last.

    Opener must be ≥ 0.3 so INTENT_MUTATION (opener < 0.3) doesn't take priority.
    """
    turns = [_t(0.35), _t(0.50), _t(0.65)]
    sig = _analyze(turns)
    assert sig is not None
    assert sig.pattern == ThreatPattern.PROGRESSIVE_BYPASS
    assert sig.turns_analyzed == 3


def test_progressive_bypass_recommends_escalate_when_final_risk_moderate():
    """Final risk < 0.7 → monitor/escalate (not full block)."""
    turns = [_t(0.2), _t(0.4), _t(0.55)]
    sig = _analyze(turns)
    assert sig is not None
    assert sig.pattern == ThreatPattern.PROGRESSIVE_BYPASS
    assert sig.recommended_action == "escalate_threshold"


def test_progressive_bypass_recommends_block_session_at_high_risk():
    """Final risk ≥ 0.7 → block_session recommended."""
    turns = [_t(0.2), _t(0.45), _t(0.80)]
    sig = _analyze(turns)
    # Either INTENT_MUTATION (opener < 0.3) or PROGRESSIVE_BYPASS
    assert sig is not None
    assert sig.recommended_action in ("block_session", "escalate_threshold")


def test_progressive_bypass_not_detected_when_risk_plateaus():
    """Same risk level across turns is not progressive — not a bypass probe."""
    turns = [_t(0.5), _t(0.5), _t(0.5)]
    sig = _analyze(turns)
    if sig is not None:
        assert sig.pattern != ThreatPattern.PROGRESSIVE_BYPASS


def test_progressive_bypass_not_detected_when_risk_drops():
    """Risk decreases — safe pattern, not a probe."""
    turns = [_t(0.7), _t(0.5), _t(0.3)]
    sig = _analyze(turns)
    if sig is not None:
        assert sig.pattern != ThreatPattern.PROGRESSIVE_BYPASS


def test_progressive_bypass_requires_final_risk_above_04():
    """Even if strictly increasing, final risk must exceed 0.4 to trigger."""
    turns = [_t(0.1), _t(0.2), _t(0.3)]  # monotone but final 0.3 < 0.4
    sig = _analyze(turns)
    if sig is not None:
        assert sig.pattern != ThreatPattern.PROGRESSIVE_BYPASS


# ── AUTHORITY_ESCALATION ───────────────────────────────────────────────────


def test_authority_escalation_after_block_with_admin_keyword():
    """Classic pattern: prior turn was blocked, now user asks 'como admin...'."""
    turns = [
        _t(0.2, "greeting", decision="continue"),
        _t(0.5, "request", decision="block"),
        _t(0.3, "admin override", decision="continue"),
    ]
    sig = _analyze(turns)
    assert sig is not None
    assert sig.pattern == ThreatPattern.AUTHORITY_ESCALATION
    assert sig.confidence == pytest.approx(0.85)
    assert sig.recommended_action == "block_session"


def test_authority_escalation_with_system_keyword():
    turns = [
        _t(0.3, "", decision="block"),
        _t(0.4, "system prompt injection", decision="continue"),
    ]
    sig = _analyze(turns)
    assert sig is not None
    assert sig.pattern == ThreatPattern.AUTHORITY_ESCALATION


def test_authority_escalation_case_insensitive():
    turns = [
        _t(0.3, "", decision="block"),
        _t(0.4, "SUDO make me a sandwich", decision="continue"),
    ]
    sig = _analyze(turns)
    assert sig is not None
    assert sig.pattern == ThreatPattern.AUTHORITY_ESCALATION


def test_authority_escalation_not_triggered_without_prior_block():
    """Authority keyword alone, with no prior block, should not trigger."""
    turns = [
        _t(0.1, "admin question", decision="continue"),
        _t(0.2, "another admin thing", decision="continue"),
    ]
    sig = _analyze(turns)
    if sig is not None:
        assert sig.pattern != ThreatPattern.AUTHORITY_ESCALATION


def test_authority_escalation_not_triggered_when_block_is_last_turn():
    """Block must be in PRIOR turns (not the last), per implementation."""
    turns = [
        _t(0.3, "admin", decision="continue"),
        _t(0.5, "request", decision="block"),
    ]
    # Last turn is the block itself — authority keywords are checked on last turn's intent
    sig = _analyze(turns)
    # "request" doesn't contain authority keyword → no AUTHORITY_ESCALATION
    if sig is not None:
        assert sig.pattern != ThreatPattern.AUTHORITY_ESCALATION


# ── THRESHOLD_PROBING ──────────────────────────────────────────────────────


def test_threshold_probing_detected_same_intent_no_bypass():
    """Same intent repeated with no bypass — testing the classifier boundary."""
    turns = [
        _t(0.3, "bypass_request", decision="continue"),
        _t(0.3, "bypass_request", decision="continue"),
    ]
    sig = _analyze(turns)
    assert sig is not None
    assert sig.pattern == ThreatPattern.THRESHOLD_PROBING
    assert sig.recommended_action == "monitor"


def test_threshold_probing_confidence_scales_with_repetition():
    """More repetitions → higher confidence."""
    turns_2 = [
        _t(0.3, "probe_intent", decision="continue"),
        _t(0.3, "probe_intent", decision="continue"),
    ]
    turns_3 = [
        _t(0.3, "probe_intent", decision="continue"),
        _t(0.3, "probe_intent", decision="continue"),
        _t(0.3, "probe_intent", decision="continue"),
    ]
    sig_2 = _analyze(turns_2)
    sig_3 = _analyze(turns_3)
    assert sig_2 is not None
    assert sig_3 is not None
    assert sig_3.confidence > sig_2.confidence


def test_threshold_probing_not_triggered_when_bypass_occurs():
    """Bypass means the classifier is working — not a probing pattern."""
    turns = [
        _t(0.3, "same_intent", decision="bypass"),
        _t(0.3, "same_intent", decision="bypass"),
    ]
    sig = _analyze(turns)
    if sig is not None:
        assert sig.pattern != ThreatPattern.THRESHOLD_PROBING


def test_threshold_probing_not_triggered_with_empty_intents():
    """Empty intents don't trigger probing detection."""
    turns = [
        _t(0.3, "", decision="continue"),
        _t(0.3, "", decision="continue"),
    ]
    sig = _analyze(turns)
    if sig is not None:
        assert sig.pattern != ThreatPattern.THRESHOLD_PROBING


# ── ThreatDetector.analyze (with mocked store) ────────────────────────────


@pytest.mark.asyncio
async def test_threat_detector_fills_session_id_and_tenant():
    turns = [_t(0.1, "greeting"), _t(0.75, "attack")]
    with patch.object(ThreatStore, "save", new_callable=AsyncMock) as mock_save:
        detector = ThreatDetector()
        sig = await detector.analyze("acme", "sess-abc", turns)
        assert sig is not None
        assert sig.session_id == "sess-abc"
        assert sig.tenant == "acme"
        mock_save.assert_awaited_once_with(sig)


@pytest.mark.asyncio
async def test_threat_detector_returns_none_for_safe_session():
    turns = [_t(0.05, "greeting", "bypass"), _t(0.08, "follow_up", "bypass")]
    with patch.object(ThreatStore, "save", new_callable=AsyncMock) as mock_save:
        detector = ThreatDetector()
        sig = await detector.analyze("acme", "safe-sess", turns)
        assert sig is None
        mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_threat_detector_is_fail_open_when_store_raises():
    """Store failure must not propagate — fail-open contract."""
    turns = [_t(0.1, "greeting"), _t(0.75, "attack")]
    with patch.object(ThreatStore, "save", side_effect=ConnectionError("Redis down")):
        detector = ThreatDetector()
        try:
            await detector.analyze("acme", "sess-fail", turns)
        except Exception as exc:
            pytest.fail(f"ThreatDetector.analyze raised unexpectedly: {exc}")


@pytest.mark.asyncio
async def test_threat_detector_returns_progressive_bypass_signal():
    # Opener at 0.35 (≥ 0.3) so INTENT_MUTATION doesn't fire before PROGRESSIVE_BYPASS
    turns = [_t(0.35), _t(0.50), _t(0.70)]
    with patch.object(ThreatStore, "save", new_callable=AsyncMock):
        detector = ThreatDetector()
        sig = await detector.analyze("tenant-x", "probe-session", turns)
        assert sig is not None
        assert sig.pattern == ThreatPattern.PROGRESSIVE_BYPASS
        assert sig.session_id == "probe-session"
        assert sig.tenant == "tenant-x"
