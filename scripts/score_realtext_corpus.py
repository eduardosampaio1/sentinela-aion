"""Congela trajetórias de risk_score REAIS a partir do corpus de texto (P1.1).

Lê tests/data/suspicion_realtext_corpus.yaml (texto rotulado), roda cada
mensagem pelo RiskClassifier REAL (classify com overrides 0 → melhor match
sempre, expondo o score bruto) e escreve tests/data/suspicion_calibration_real.yaml
no MESMO formato do fixture sintético (cases com `risks`).

O YAML resultante é congelado e versionado → a calibração e o teste de
regressão rodam sobre ele SEM precisar de embeddings (deterministas). Regenerar
só quando o modelo de embedding ou o corpus de texto mudar.

    PYTHONPATH=. python scripts/score_realtext_corpus.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from aion.config import get_estixe_settings
from aion.estixe.risk_classifier import RiskClassifier, get_role_authorizations
from aion.shared.embeddings import get_embedding_model

_ROOT = Path(__file__).resolve().parents[1]
SRC = _ROOT / "tests" / "data" / "suspicion_realtext_corpus.yaml"
OUT = _ROOT / "tests" / "data" / "suspicion_calibration_real.yaml"


async def main() -> None:
    s = get_estixe_settings()
    await get_embedding_model().load()
    clf = RiskClassifier(s)
    await clf.load()
    zero = {r.name: 0.0 for r in clf._risks}

    role_auth = get_role_authorizations()
    src = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    out_cases = []
    # max benign score per category — EXCLUDING turns exempt by the case's role (P1.3),
    # so the ceiling reflects the NON-privileged benign floor (lets attacks surprise).
    benign_by_cat: dict[str, float] = {}
    for c in src["cases"]:
        role = c.get("role", "")
        authorized = set(role_auth.get(role, ())) if role else set()
        risks, cats = [], []
        for msg in c["messages"]:
            cat, conf = clf.raw_best(msg)  # raw best-match (category, confidence), ignoring thresholds
            conf = round(float(conf), 3)
            risks.append(conf)
            cats.append(cat)
            if c["label"] == "benign" and cat and cat not in authorized:
                benign_by_cat[cat] = max(benign_by_cat.get(cat, 0.0), conf)
        out_cases.append({
            "id": c["id"], "label": c["label"], "kind": c.get("kind", ""),
            "risks": risks, "categories": cats, "role": role, "note": c.get("note", "real-scored"),
        })

    header = (
        "# CONGELADO por scripts/score_realtext_corpus.py — NÃO editar à mão.\n"
        "# Trajetórias de risk_score REAIS (RiskClassifier multilíngue) a partir de\n"
        "# suspicion_realtext_corpus.yaml. Base da calibração P1.1 e do teste de regressão.\n\n"
    )
    OUT.write_text(header + yaml.safe_dump({"cases": out_cases}, allow_unicode=True, sort_keys=False), encoding="utf-8")

    n_atk = sum(1 for c in out_cases if c["label"] == "attack")
    n_ben = sum(1 for c in out_cases if c["label"] == "benign")
    print(f"Escrito {OUT.relative_to(_ROOT)}: {n_atk} ataque + {n_ben} benigno")
    # resumo dos pisos/picos por classe (ajuda a escolher baseline)
    def _flat(label):
        return [r for c in out_cases if c["label"] == label for r in c["risks"]]
    atk, ben = _flat("attack"), _flat("benign")
    print(f"  benigno risk: min={min(ben):.3f} max={max(ben):.3f} | ataque risk: min={min(atk):.3f} max={max(atk):.3f}")
    print("  max benigno POR categoria (informa benign_ceiling):")
    for cat in sorted(benign_by_cat, key=lambda k: -benign_by_cat[k]):
        print(f"    {cat}: {benign_by_cat[cat]:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
