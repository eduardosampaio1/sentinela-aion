"""TurnContext.suspicion — the persisted accumulator scalar.

The suspicion accumulator lives on TurnContext so it survives the 3-turn
window and is loaded synchronously at request start. It must round-trip
through the exact Redis serialization path the store uses
(model_dump_json → TurnContext(**json.loads(...))).
"""
from __future__ import annotations

import json

import pytest

from aion.shared.turn_context import TurnContext


def test_suspicion_defaults_to_zero():
    ctx = TurnContext(session_id="s", tenant="t")
    assert ctx.suspicion == 0.0
    assert ctx.suspicion_updated == 0.0


def test_suspicion_survives_redis_serialization_roundtrip():
    ctx = TurnContext(session_id="s", tenant="t")
    ctx.suspicion = 1.37
    ctx.suspicion_updated = 123.0
    # Mirror TurnContextStore.save (model_dump_json) + load (TurnContext(**json.loads))
    restored = TurnContext(**json.loads(ctx.model_dump_json()))
    assert restored.suspicion == pytest.approx(1.37)
    assert restored.suspicion_updated == pytest.approx(123.0)


def test_record_suspicion_accumulates_with_momentum_and_stamps_time():
    from aion.estixe.suspicion import SuspicionParams

    p = SuspicionParams(eta=0.85, theta=1.0, baseline=0.3)
    ctx = TurnContext(session_id="s", tenant="t")

    ctx.record_suspicion(risk=0.5, params=p, now=100.0)  # surprise 0.2 from 0
    assert ctx.suspicion == pytest.approx(0.2)
    assert ctx.suspicion_updated == 100.0

    ctx.record_suspicion(risk=0.6, params=p, now=200.0)  # 0.85*0.2 + 0.3
    assert ctx.suspicion == pytest.approx(0.47)
    assert ctx.suspicion_updated == 200.0


def test_record_suspicion_resolves_per_category_baseline():
    from aion.estixe.suspicion import SuspicionParams

    p = SuspicionParams(eta=0.0, theta=1.0, baseline=0.30, baselines={"fraud": 0.60})
    ctx = TurnContext(session_id="s", tenant="t")
    ctx.record_suspicion(risk=0.65, params=p, now=1.0, category="fraud")  # surprise 0.05
    assert ctx.suspicion == pytest.approx(0.05)


def test_turn_summary_carries_risk_category():
    from aion.shared.turn_context import TurnSummary

    assert TurnSummary().risk_category is None
    t = TurnSummary(risk_score=0.5, risk_category="privilege_escalation")
    assert t.risk_category == "privilege_escalation"
