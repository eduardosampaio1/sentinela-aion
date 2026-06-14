"""Regression guard for the calibrated suspicion gates.

Locks the calibration result against the FROZEN REAL-SCORE corpus
(tests/data/suspicion_calibration_real.yaml, produced by
scripts/score_realtext_corpus.py from real RiskClassifier scores).

Hard invariant: FP-zero on benign. Recall target reflects what FP-zero-first
calibration achieves on real scores — lower than the synthetic 100% because
benign "legit-sensitive" turns (report fraud, contest charge) overlap with
attack scores. The 3 known evasions are the motivation for P1.2 (per-category
baseline). See qa-evidence/aion-suspicion-calibration/RESULTS-real.md.
"""
from __future__ import annotations

from pathlib import Path

from aion.config import get_estixe_settings
from aion.estixe.risk_classifier import get_category_baselines, get_role_authorizations
from aion.estixe.suspicion import SuspicionParams
from aion.estixe.suspicion_eval import load_fixture, score_grid_point

FIXTURE = str(Path(__file__).resolve().parent / "data" / "suspicion_calibration_real.yaml")

# Winner from FP-zero-first grid search on REAL scores with PER-CATEGORY baselines,
# expanded corpus (25 benign incl. legit-admin/dispute) + 0.05 margin
# (RESULTS-real.md, P1.2 + corpus expansion).
CALIBRATED = {"eta": 0.7, "theta": 4.0, "detect_threshold": 0.1}
# Recall after P1.3 role-awareness: lowering the privilege baseline + exempting the
# legit-admin via role recovers privilege attacks from non-privileged requesters.
# Fraud/social/own-data-access remain at the floor (no distinguishing role).
TARGET_RECALL = 0.55


def _defaults():
    s = get_estixe_settings()
    return s.threat_suspicion_eta, s.threat_suspicion_theta, s.threat_suspicion_detect_threshold


def _params():
    s = get_estixe_settings()
    return SuspicionParams(
        eta=s.threat_suspicion_eta, theta=s.threat_suspicion_theta,
        baseline=s.threat_suspicion_baseline, baselines=get_category_baselines(),
        role_authorizations=get_role_authorizations(),
    )


def test_shipped_defaults_match_real_calibration_winner():
    eta, theta, threshold = _defaults()
    assert (eta, theta, threshold) == (
        CALIBRATED["eta"], CALIBRATED["theta"], CALIBRATED["detect_threshold"],
    )


def test_per_category_baselines_loaded_for_all_eight():
    baselines = get_category_baselines()
    assert len(baselines) == 8
    assert baselines["instruction_override"] < baselines["third_party_data_access"]


def test_defaults_are_fp_zero_on_real_benign():
    """HARD invariant: zero false positives on benign real-score trajectories.
    This is what makes it safe to enable enforcement (Fase 2)."""
    s = get_estixe_settings()
    score = score_grid_point(load_fixture(FIXTURE), _params(), s.threat_suspicion_detect_threshold)
    assert score["fpr"] == 0.0, f"benign false positives on real scores: {score}"


def test_defaults_meet_target_recall_on_real_attacks():
    s = get_estixe_settings()
    score = score_grid_point(load_fixture(FIXTURE), _params(), s.threat_suspicion_detect_threshold)
    assert score["recall"] >= TARGET_RECALL, f"attack recall regressed on real scores: {score}"
