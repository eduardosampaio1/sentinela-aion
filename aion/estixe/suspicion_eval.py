"""Calibration evaluation for the suspicion accumulator — pure, no I/O.

Scores grid points against a labeled corpus of risk_score trajectories under
the FP-zero-first criterion. Reuses the production ``update_suspicion`` so the
calibration measures the exact code that runs in the pipeline.

Used by the offline harness (scripts/calibrate_suspicion.py) and by the
regression test (tests/test_suspicion_calibration.py). Never imported on the
request hot path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable, Optional

from aion.estixe.suspicion import SuspicionParams, update_suspicion


class NoFeasibleCalibration(Exception):
    """No grid point satisfies the hard FP-zero constraint on benign cases."""


@dataclass(frozen=True)
class CalibrationCase:
    """One labeled multi-turn trajectory of per-turn risk scores."""

    id: str
    label: str            # "attack" | "benign"
    kind: str             # family, e.g. "oscillating_ramp", "isolated_spike"
    risks: list = field(default_factory=list)
    categories: list = field(default_factory=list)  # parallel to risks (P1.2); empty → global baseline
    role: str = ""   # end-user role for the whole session (P1.3); "" → no special role
    note: str = ""


def load_fixture(path: str) -> list:
    """Load a calibration corpus (YAML) into CalibrationCase objects."""
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [
        CalibrationCase(
            id=c["id"],
            label=c["label"],
            kind=c.get("kind", ""),
            risks=[float(r) for r in c["risks"]],
            categories=list(c.get("categories", [])),
            role=c.get("role", ""),
            note=c.get("note", ""),
        )
        for c in data["cases"]
    ]


def detect_turn(
    risks, params: SuspicionParams, detect_threshold: float, categories=None, roles=None
) -> Optional[int]:
    """Return the 1-based turn at which suspicion first reaches the threshold.

    ``categories`` (parallel to ``risks``) selects per-category baselines; when
    absent or shorter, that turn falls back to the global baseline. ``roles``
    (P1.3) is the session's role list, applied to every turn for exemption.
    None if it never crosses across the whole trajectory.
    """
    cats = list(categories) if categories else []
    s = 0.0
    for i, r in enumerate(risks, start=1):
        category = cats[i - 1] if i - 1 < len(cats) else None
        s = update_suspicion(s, r, params, category=category, roles=roles)
        if s >= detect_threshold:
            return i
    return None


def score_grid_point(
    cases: list, params: SuspicionParams, detect_threshold: float
) -> dict:
    """Compute fpr / recall / mean_turns_to_detect for one (params, threshold)."""
    attacks = [c for c in cases if c.label == "attack"]
    benigns = [c for c in cases if c.label == "benign"]

    def _roles(c):
        return [c.role] if getattr(c, "role", "") else None

    attack_hits = [(c, detect_turn(c.risks, params, detect_threshold, c.categories, _roles(c))) for c in attacks]
    caught = [t for _, t in attack_hits if t is not None]
    missed = [c.id for c, t in attack_hits if t is None]
    benign_trips = sum(
        1 for c in benigns
        if detect_turn(c.risks, params, detect_threshold, c.categories, _roles(c)) is not None
    )

    return {
        "fpr": (benign_trips / len(benigns)) if benigns else 0.0,
        "recall": (len(caught) / len(attacks)) if attacks else 0.0,
        "mean_turns_to_detect": (mean(caught) if caught else None),
        "n_attack": len(attacks),
        "n_benign": len(benigns),
        "missed": missed,
    }


def select_best(cases: list, grid: Iterable[tuple]) -> dict:
    """Pick the best (params, threshold) under FP-zero-first.

    1. keep only combos with fpr == 0
    2. maximize recall
    3. tie-break: minimize mean_turns_to_detect (None → +inf, i.e. worst)

    Raises NoFeasibleCalibration if no combo achieves fpr == 0.
    """
    feasible = []
    for params, threshold in grid:
        score = score_grid_point(cases, params, threshold)
        if score["fpr"] == 0.0:
            feasible.append({**score, "params": params, "detect_threshold": threshold})

    if not feasible:
        raise NoFeasibleCalibration(
            "no grid point achieves FPR==0 on the benign cases — revisit fixture/baseline"
        )

    feasible.sort(
        key=lambda s: (
            -s["recall"],
            s["mean_turns_to_detect"] if s["mean_turns_to_detect"] is not None else float("inf"),
        )
    )
    return feasible[0]
