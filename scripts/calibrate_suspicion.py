"""Offline calibration harness for the suspicion accumulator (Titans P0).

Grid-searches (eta, theta, baseline, detect_threshold) against the labeled
corpus under the FP-zero-first criterion and writes a report. NOT used at
runtime — run it manually, review the report, then apply the winning values to
EstixeSettings by hand.

    python scripts/calibrate_suspicion.py
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

from aion.estixe.risk_classifier import get_category_baselines, get_role_authorizations
from aion.estixe.suspicion import SuspicionParams
from aion.estixe.suspicion_eval import (
    NoFeasibleCalibration,
    load_fixture,
    score_grid_point,
    select_best,
)

_ROOT = Path(__file__).resolve().parents[1]
# Fixture: argv[1] override, else the frozen real-score corpus if present, else synthetic.
_REAL = _ROOT / "tests" / "data" / "suspicion_calibration_real.yaml"
_SYNTH = _ROOT / "tests" / "data" / "suspicion_calibration.yaml"
FIXTURE = Path(sys.argv[1]) if len(sys.argv) > 1 else (_REAL if _REAL.exists() else _SYNTH)
REPORT_DIR = _ROOT / "qa-evidence" / "aion-suspicion-calibration"

# P1.2: per-category baselines are FIXED from the taxonomy (not grid-searched).
# Only eta/theta/detect_threshold are tuned.
_BASELINES = get_category_baselines()
_ROLE_AUTH = get_role_authorizations()  # P1.3: role exemptions applied in the eval
_GLOBAL_FALLBACK_BASELINE = 0.5  # used only if a turn has no category (raw_best == "")
ETA_GRID = [0.70, 0.80, 0.85, 0.90, 0.95]
THETA_GRID = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]
THRESHOLD_GRID = [0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0]


def build_grid():
    for eta, theta, threshold in itertools.product(ETA_GRID, THETA_GRID, THRESHOLD_GRID):
        yield (
            SuspicionParams(
                eta=eta, theta=theta,
                baseline=_GLOBAL_FALLBACK_BASELINE, baselines=_BASELINES,
                role_authorizations=_ROLE_AUTH,
            ),
            threshold,
        )


def main() -> None:
    cases = load_fixture(str(FIXTURE))
    grid = list(build_grid())

    try:
        best = select_best(cases, grid)
    except NoFeasibleCalibration as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1)

    p = best["params"]
    miss = best["missed"]
    n_combos = len(grid)
    n_feasible = sum(
        1 for params, thr in grid if score_grid_point(cases, params, thr)["fpr"] == 0.0
    )

    lines = [
        "# Calibração do acumulador de suspeita — RESULTS",
        "",
        f"- Fixture: `{FIXTURE.relative_to(_ROOT)}` "
        f"({best['n_attack']} ataque + {best['n_benign']} benigno)",
        f"- Grid avaliado: {n_combos} combos · {n_feasible} satisfazem FP-zero",
        "- Critério: FP-zero -> max recall -> min turns-to-detect",
        "",
        "## Vencedor",
        "",
        f"- **eta = {p.eta}**, **theta = {p.theta}**, **detect_threshold = {best['detect_threshold']}** "
        f"(baseline = POR-CATEGORIA, fixo na taxonomia `suspicion_baselines`)",
        f"- recall = {best['recall']:.3f} · fpr = {best['fpr']:.3f} · "
        f"mean_turns_to_detect = {best['mean_turns_to_detect']}",
        f"- ataques não detectados: {miss if miss else 'nenhum'}",
        "",
        "## Aplicar (gate humano)",
        "",
        "Atualizar em `aion/config.py` (EstixeSettings) — baselines ficam na taxonomia:",
        "```",
        f"threat_suspicion_eta = {p.eta}",
        f"threat_suspicion_theta = {p.theta}",
        f"threat_suspicion_detect_threshold = {best['detect_threshold']}",
        "```",
    ]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "-real" if FIXTURE == _REAL else ""
    report_path = REPORT_DIR / f"RESULTS{suffix}.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print(f"\nReport escrito em {report_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
