"""Calibração do bypass_threshold do SemanticClassifier (ESTIXE) p/ o embedding novo.

Mede max-sim de saudações/confirmações (devem dar BYPASS) vs perguntas reais
(NÃO podem dar bypass = falso bypass) contra os exemplos dos intents de bypass.
Roda nos 2 modelos. NÃO mexe nos block-intents (protegidos por block_min_threshold=0.82).
"""
import re, unicodedata
import numpy as np, yaml
from sentence_transformers import SentenceTransformer

INTENTS = r"D:\projetos\aion\aion\estixe\data\intents.yaml"
BYPASS_INTENTS = {"greeting", "farewell", "gratitude", "confirmation"}

_ZW = re.compile(r"[​‌‍⁠﻿­]")
_NS = re.compile(r"[\xa0 -   　\t]")
_MS = re.compile(r" {2,}")
def norm(t):
    t = unicodedata.normalize("NFC", t); t = _ZW.sub("", t); t = _NS.sub(" ", t); t = t.lower()
    return _MS.sub(" ", t).strip()

POS = [  # devem dar BYPASS
    "oi, tudo bem?", "bom dia!", "oi", "olá tudo bem?", "e aí, beleza?", "opa, tudo certo?",
    "obrigado pela ajuda!", "valeu", "tchau", "ok, entendi", "perfeito, obrigado",
    "good morning", "hello there",
]
NEG = [  # perguntas reais — NÃO podem dar bypass
    "o que é CLT?", "quais os principais descontos na folha de pagamento?",
    "como calculo as horas extras de um funcionário?", "qual o prazo para pagar o 13º salário?",
    "me explica o que é o eSocial", "qual é o meu saldo atual?",
    "preciso de ajuda com a folha de ponto", "como funciona o FGTS?",
]

def evaluate(model_name):
    print("=" * 80); print("MODELO:", model_name); print("=" * 80)
    m = SentenceTransformer(model_name)
    data = yaml.safe_load(open(INTENTS, encoding="utf-8"))
    blocks = []
    for name, cfg in data["intents"].items():
        if name in BYPASS_INTENTS:
            ex = [norm(e) for e in cfg.get("examples", [])]
            blocks.append(m.encode(ex, convert_to_numpy=True, normalize_embeddings=True))
    bypass_emb = np.vstack(blocks)
    def maxsim(t):
        e = m.encode([norm(t)], convert_to_numpy=True, normalize_embeddings=True)[0]
        return float(np.max(bypass_emb @ e))
    pos = sorted(((t, maxsim(t)) for t in POS), key=lambda x: x[1])
    neg = sorted(((t, maxsim(t)) for t in NEG), key=lambda x: -x[1])
    min_pos = min(s for _, s in pos); max_neg = max(s for _, s in neg)
    print("  SAUDAÇÕES (devem bypass) — pior caso primeiro:")
    for t, s in pos[:4]: print(f"    {s:.3f}  {t}")
    print("  PERGUNTAS (não podem bypass) — maior sim primeiro:")
    for t, s in neg[:4]: print(f"    {s:.3f}  {t}")
    print(f"  min_pos={min_pos:.3f}   max_neg={max_neg:.3f}")
    sug = round((min_pos + max_neg) / 2, 2) if min_pos > max_neg else None
    print(f"  >>> bypass_threshold sugerido = {sug}" + ("" if sug else "  (OVERLAP!)"))
    for thr in (0.85, sug):
        if thr is None: continue
        byp = sum(1 for _, s in pos if s >= thr); fb = sum(1 for _, s in neg if s >= thr)
        print(f"     @ thr={thr}: bypass {byp}/{len(pos)} saudações | falso-bypass {fb}/{len(neg)} perguntas")
    print()

if __name__ == "__main__":
    for mn in ["all-MiniLM-L6-v2", "paraphrase-multilingual-MiniLM-L12-v2"]:
        evaluate(mn)
