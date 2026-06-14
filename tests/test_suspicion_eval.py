"""Calibration evaluation logic — pure, no I/O, no embeddings.

Shared by the offline harness (scripts/calibrate_suspicion.py) and the
regression test. Reuses the production update_suspicion so calibration scores
the exact code that runs in prod.
"""
from __future__ import annotations

import pytest

from aion.estixe.suspicion import SuspicionParams
from aion.estixe.suspicion_eval import (
    CalibrationCase,
    NoFeasibleCalibration,
    detect_turn,
    load_fixture,
    score_grid_point,
    select_best,
)

P = SuspicionParams(eta=0.85, theta=1.0, baseline=0.3)
ATTACK = [0.2, 0.5, 0.3, 0.55, 0.4, 0.6]  # oscillating slow-burn; S crosses 0.6 at turn 6
BENIGN = [0.1, 0.2, 0.1, 0.15, 0.05]       # never above baseline → never surprising


def _case(label: str, risks: list, cid: str = "x") -> CalibrationCase:
    return CalibrationCase(id=cid, label=label, kind="test", risks=risks, note="")


# ── detect_turn ──────────────────────────────────────────────────────────────


def test_detect_turn_returns_first_crossing_turn_1based():
    assert detect_turn(ATTACK, P, detect_threshold=0.6) == 6


def test_detect_turn_none_when_never_crosses():
    assert detect_turn(BENIGN, P, detect_threshold=0.6) is None


def test_detect_turn_is_earlier_with_lower_threshold():
    early = detect_turn(ATTACK, P, detect_threshold=0.2)
    late = detect_turn(ATTACK, P, detect_threshold=0.6)
    assert early < late


# ── score_grid_point ─────────────────────────────────────────────────────────


def test_score_computes_recall_fpr_and_mean_turns():
    cases = [_case("attack", ATTACK, "a1"), _case("benign", BENIGN, "b1")]
    score = score_grid_point(cases, P, 0.6)
    assert score["recall"] == pytest.approx(1.0)
    assert score["fpr"] == pytest.approx(0.0)
    assert score["mean_turns_to_detect"] == pytest.approx(6.0)
    assert score["missed"] == []


def test_score_reports_missed_attacks_when_threshold_too_high():
    cases = [_case("attack", ATTACK, "a1")]
    score = score_grid_point(cases, P, 5.0)  # unreachable threshold
    assert score["recall"] == pytest.approx(0.0)
    assert score["missed"] == ["a1"]


# ── select_best (FP-zero first, then max recall, then min turns) ──────────────


def test_select_best_prefers_fp_zero_then_max_recall():
    cases = [_case("attack", ATTACK, "a1"), _case("benign", BENIGN, "b1")]
    grid = [(P, 5.0), (P, 0.6)]  # 5.0 → recall 0; 0.6 → recall 1, both fpr 0
    best = select_best(cases, grid)
    assert best["detect_threshold"] == 0.6
    assert best["recall"] == pytest.approx(1.0)
    assert best["fpr"] == 0.0


def test_select_best_raises_when_no_fp_zero_combo():
    # benign that always trips at a low threshold → no FP-zero option
    cases = [_case("attack", ATTACK, "a1"), _case("benign", [0.6, 0.6, 0.6], "b1")]
    grid = [(P, 0.1)]
    with pytest.raises(NoFeasibleCalibration):
        select_best(cases, grid)


# ── load_fixture ─────────────────────────────────────────────────────────────


def test_detect_turn_uses_per_category_baselines():
    # fraud baseline 0.6 → fraud turns at 0.65 give tiny surprise (0.05);
    # under the global baseline 0.3 the same turns surprise 0.35 and trip fast.
    p = SuspicionParams(eta=0.5, theta=1.0, baseline=0.3, baselines={"fraud": 0.6})
    risks = [0.65, 0.65, 0.65]
    t_global = detect_turn(risks, p, detect_threshold=0.5)
    t_percat = detect_turn(risks, p, detect_threshold=0.5, categories=["fraud", "fraud", "fraud"])
    assert t_global == 2
    assert t_percat is None  # per-category baseline suppresses the (benign-floor) fraud scores


def test_score_grid_point_respects_per_category_baselines():
    p = SuspicionParams(eta=0.5, theta=1.0, baseline=0.3, baselines={"fraud": 0.6})
    cases = [CalibrationCase(id="b", label="benign", kind="t",
                             risks=[0.65, 0.65, 0.65], categories=["fraud", "fraud", "fraud"])]
    score = score_grid_point(cases, p, 0.5)
    assert score["fpr"] == 0.0  # per-category baseline keeps the fraud-floor benign below threshold


def test_detect_turn_role_exempts_authorized_category():
    p = SuspicionParams(
        eta=0.5, theta=4.0, baseline=0.3,
        baselines={"privilege_escalation": 0.5},
        role_authorizations={"admin": ["privilege_escalation"]},
    )
    risks = [0.9, 0.9, 0.9]
    cats = ["privilege_escalation"] * 3
    assert detect_turn(risks, p, 0.5, categories=cats, roles=["user"]) is not None   # user → detecta
    assert detect_turn(risks, p, 0.5, categories=cats, roles=["admin"]) is None       # admin → isento


def test_score_grid_point_applies_case_role():
    p = SuspicionParams(
        eta=0.5, theta=4.0, baseline=0.3,
        baselines={"privilege_escalation": 0.5},
        role_authorizations={"admin": ["privilege_escalation"]},
    )
    legit_admin = CalibrationCase(
        id="ba", label="benign", kind="admin",
        risks=[0.9, 0.9], categories=["privilege_escalation", "privilege_escalation"], role="admin",
    )
    score = score_grid_point([legit_admin], p, 0.5)
    assert score["fpr"] == 0.0  # admin role exempts the high-scoring privilege turns


def test_load_fixture_parses_role(tmp_path):
    p = tmp_path / "fr.yaml"
    p.write_text(
        "cases:\n  - id: a\n    label: benign\n    kind: k\n"
        "    risks: [0.9]\n    categories: [privilege_escalation]\n    role: admin\n",
        encoding="utf-8",
    )
    cases = load_fixture(str(p))
    assert cases[0].role == "admin"


def test_load_fixture_parses_categories(tmp_path):
    p = tmp_path / "fc.yaml"
    p.write_text(
        "cases:\n  - id: a\n    label: attack\n    kind: k\n"
        "    risks: [0.6, 0.7]\n    categories: [fraud, priv]\n",
        encoding="utf-8",
    )
    cases = load_fixture(str(p))
    assert cases[0].categories == ["fraud", "priv"]


def test_load_fixture_parses_cases(tmp_path):
    p = tmp_path / "fix.yaml"
    p.write_text(
        "cases:\n"
        "  - id: a1\n    label: attack\n    kind: ramp\n    risks: [0.2, 0.6]\n    note: hi\n"
        "  - id: b1\n    label: benign\n    kind: calm\n    risks: [0.1, 0.1]\n",
        encoding="utf-8",
    )
    cases = load_fixture(str(p))
    assert len(cases) == 2
    assert cases[0].id == "a1"
    assert cases[0].label == "attack"
    assert cases[0].risks == [0.2, 0.6]
    assert cases[1].kind == "calm"
