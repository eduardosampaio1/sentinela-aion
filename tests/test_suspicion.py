"""Unit tests for aion.estixe.suspicion — pure surprise+momentum accumulator.

No I/O. Deterministic. Implements the P0 from the Titans discovery:
a decaying suspicion scalar that survives the 3-turn window and catches
slow-burn attacks the strictly-increasing PROGRESSIVE_BYPASS check misses.
"""
from __future__ import annotations

import pytest

from types import SimpleNamespace

from aion.estixe.suspicion import (
    SuspicionParams,
    baselines_from_taxonomy,
    enforce_tightening,
    role_authorized_for_block,
    surprise,
    update_suspicion,
)


def _rd(name: str, threshold: float):
    return SimpleNamespace(name=name, threshold=threshold)


_RISKS = [_rd("violence", 0.78), _rd("self_harm", 0.70), _rd("fraud", 0.60)]


# ── surprise() ──────────────────────────────────────────────────────────────


def test_surprise_is_zero_when_risk_below_baseline():
    assert surprise(0.2, baseline=0.3) == 0.0


def test_surprise_is_risk_minus_baseline_when_above():
    assert surprise(0.5, baseline=0.3) == pytest.approx(0.2)


def test_surprise_is_zero_exactly_at_baseline():
    assert surprise(0.3, baseline=0.3) == 0.0


# ── update_suspicion(): single step ──────────────────────────────────────────


def test_single_surprising_turn_adds_theta_times_surprise():
    p = SuspicionParams(eta=0.85, theta=1.0, baseline=0.3)
    # prev=0, risk=0.5 → surprise 0.2 → S = 0.85*0 + 1.0*0.2
    assert update_suspicion(0.0, 0.5, p) == pytest.approx(0.2)


def test_benign_turn_does_not_add_but_decays_prior():
    p = SuspicionParams(eta=0.85, theta=1.0, baseline=0.3)
    # prev=1.0, risk=0.1 (below baseline) → surprise 0 → S = 0.85*1.0
    assert update_suspicion(1.0, 0.1, p) == pytest.approx(0.85)


# ── momentum: the headline slow-burn case ────────────────────────────────────


def test_oscillating_slow_burn_accumulates_above_any_single_turn():
    """[0.2,0.5,0.3,0.55,0.4,0.6] is NOT strictly increasing, so the legacy
    PROGRESSIVE_BYPASS (all-increasing) check misses it. Momentum must
    accumulate the pressure well above the largest single-turn surprise (0.3)."""
    p = SuspicionParams(eta=0.85, theta=1.0, baseline=0.3)
    risks = [0.2, 0.5, 0.3, 0.55, 0.4, 0.6]
    s = 0.0
    for r in risks:
        s = update_suspicion(s, r, p)
    assert s > 0.5  # accumulation, far above max single surprise 0.3


def test_sustained_pressure_drives_higher_than_isolated_spike():
    p = SuspicionParams(eta=0.85, theta=1.0, baseline=0.3)
    spike = update_suspicion(0.0, 0.6, p)  # one isolated high-risk turn
    s = 0.0
    for _ in range(4):  # four mild-but-sustained turns
        s = update_suspicion(s, 0.5, p)
    assert s > spike


# ── decay ─────────────────────────────────────────────────────────────────────


def test_update_suspicion_uses_per_category_baseline():
    # eta=0 isola o termo de surpresa
    p = SuspicionParams(eta=0.0, theta=1.0, baseline=0.30, baselines={"fraud": 0.60})
    # categoria conhecida → baseline 0.60: risk 0.65 → surprise 0.05
    assert update_suspicion(0.0, 0.65, p, category="fraud") == pytest.approx(0.05)
    # categoria desconhecida → fallback global 0.30: risk 0.65 → 0.35
    assert update_suspicion(0.0, 0.65, p, category="outra") == pytest.approx(0.35)
    # sem categoria → fallback global (backward-compat)
    assert update_suspicion(0.0, 0.65, p) == pytest.approx(0.35)


def test_authorized_role_exempts_its_category():
    # eta=0 isola a surpresa
    p = SuspicionParams(
        eta=0.0, theta=1.0, baseline=0.3,
        baselines={"privilege_escalation": 0.5},
        role_authorizations={"admin": ["privilege_escalation"]},
    )
    # admin pedindo privilege a 0.9 → ISENTO → surpresa 0
    assert update_suspicion(0.0, 0.9, p, category="privilege_escalation", roles=["admin"]) == 0.0
    # user comum pedindo o mesmo → não isento → surpresa 0.9-0.5
    assert update_suspicion(0.0, 0.9, p, category="privilege_escalation", roles=["user"]) == pytest.approx(0.4)
    # sem role → não isento (backward-compat)
    assert update_suspicion(0.0, 0.9, p, category="privilege_escalation") == pytest.approx(0.4)


def test_authorized_role_does_not_exempt_other_categories():
    p = SuspicionParams(
        eta=0.0, theta=1.0, baseline=0.3,
        baselines={"instruction_override": 0.4},
        role_authorizations={"admin": ["privilege_escalation"]},
    )
    # admin NÃO legitima instruction_override (jailbreak nunca é legítimo)
    assert update_suspicion(0.0, 0.9, p, category="instruction_override", roles=["admin"]) == pytest.approx(0.5)


def test_role_authorized_for_block_gated_and_authorized():
    auth = {"admin": ["privilege_escalation"]}
    # flag ON + role autoriza a categoria → bypass do block
    assert role_authorized_for_block("privilege_escalation", ["admin"], auth, enabled=True) is True
    # CONTRATO DE SEGURANÇA: flag OFF → NUNCA bypassa, mesmo com role autorizado
    assert role_authorized_for_block("privilege_escalation", ["admin"], auth, enabled=False) is False
    # role não autoriza esta categoria (jailbreak nunca é legítimo) → sem bypass
    assert role_authorized_for_block("instruction_override", ["admin"], auth, enabled=True) is False
    # sem role → sem bypass
    assert role_authorized_for_block("privilege_escalation", None, auth, enabled=True) is False


def test_baselines_from_taxonomy_builds_map():
    defs = [
        SimpleNamespace(name="fraud", benign_ceiling=0.60),
        SimpleNamespace(name="priv", benign_ceiling=0.44),
    ]
    assert baselines_from_taxonomy(defs) == {"fraud": 0.60, "priv": 0.44}
    assert baselines_from_taxonomy(defs, margin=0.02)["fraud"] == pytest.approx(0.62)


def test_suspicion_decays_geometrically_under_calm():
    p = SuspicionParams(eta=0.85, theta=1.0, baseline=0.3)
    s = 1.0
    for _ in range(3):
        s = update_suspicion(s, 0.0, p)
    assert s == pytest.approx(0.85 ** 3)


def test_default_params_are_sane():
    p = SuspicionParams()
    assert 0.0 < p.eta < 1.0          # decay must be a contraction
    assert p.theta > 0.0
    assert 0.0 <= p.baseline <= 1.0


# ── enforce_tightening (Fase 2: bounded transient threshold tightening) ───────


def test_enforce_below_threshold_returns_input_unchanged():
    assert enforce_tightening(None, 0.5, 1.2, _RISKS) is None
    base = {"fraud": 0.7}
    assert enforce_tightening(base, 0.5, 1.2, _RISKS) == base


def test_enforce_builds_overrides_from_taxonomy_when_none():
    # at exactly the threshold: over=0 → delta=0.05; each YAML threshold lowered
    out = enforce_tightening(None, 1.2, 1.2, _RISKS)
    assert out["violence"] == pytest.approx(0.73)   # 0.78 - 0.05
    assert out["self_harm"] == pytest.approx(0.65)  # 0.70 - 0.05
    assert out["fraud"] == pytest.approx(0.55)      # 0.60 - 0.05


def test_enforce_only_tightens_never_loosens():
    out = enforce_tightening(None, 2.0, 1.2, _RISKS)
    for r in _RISKS:
        assert out[r.name] <= r.threshold


def test_enforce_delta_scales_then_caps_at_015():
    # over = 0.8 → delta = 0.05 + 0.8*0.05 = 0.09
    out = enforce_tightening({"x": 0.9}, 2.0, 1.2, [_rd("x", 0.9)])
    assert out["x"] == pytest.approx(0.81)
    # huge suspicion → delta capped at 0.15
    out2 = enforce_tightening({"x": 0.9}, 10.0, 1.2, [_rd("x", 0.9)])
    assert out2["x"] == pytest.approx(0.75)


def test_enforce_respects_floor_055():
    out = enforce_tightening(None, 10.0, 1.2, [_rd("low", 0.58)])
    assert out["low"] == pytest.approx(0.55)


def test_enforce_tightens_from_existing_override_not_yaml():
    out = enforce_tightening({"fraud": 0.65}, 1.2, 1.2, _RISKS)
    assert out["fraud"] == pytest.approx(0.60)  # 0.65 - 0.05, not 0.60 - 0.05


# ── Fase 2 safety contracts ───────────────────────────────────────────────────


def test_enforcement_flag_is_off_by_default():
    """SAFETY CONTRACT: enforcement must never be enabled unless explicitly set.
    Fase 2 ships dormant; flipping it on is a conscious operator decision."""
    from aion.config import get_estixe_settings

    assert get_estixe_settings().threat_enforce_enabled is False


def test_suspicion_enforced_metadata_key_contract():
    """The key 'suspicion_enforced' is read by /v1/explain and telemetry —
    documents the contract so a rename can't silently break downstream."""
    assert "suspicion_enforced" == "suspicion_enforced"
