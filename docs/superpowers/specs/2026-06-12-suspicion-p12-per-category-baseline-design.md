# Spec — P1.2: captura de score bruto + baseline por-categoria

**Data:** 2026-06-12 · **Branch:** `fix/estixe-ptbr-injection`
**Origem:** Smoke E2E + P1.1 revelaram (a) que a Fase 1 é inerte em produção (turno sub-threshold → `risk_confidence=0`) e (b) que baseline global custa 30% de recall.

## Objetivo

1. **Parte A (pré-requisito):** fazer o acumulador ver o **score bruto real por turno**, mesmo abaixo do threshold — sem isso a detecção não funciona em produção.
2. **Parte B:** baseline **por-categoria** (cada categoria tem seu piso benigno), recuperando recall sob FP-zero.

## Achado que motiva (Parte A)

`estixe/__init__.py:350-398`: `risk_confidence` no metadata só é setado no branch de BLOCK (critical/high acima do threshold). `classify()` retorna `None` abaixo do limiar → `pipeline.py:476` lê 0.0. Logo o acumulador recebe ~0 em todo turno sub-threshold (o caso slow-burn). Hoje só veria score num turno já bloqueado single-turn. **Fase 1 inerte em prod.**

## Parte A — Captura do score bruto

- `RiskClassifier.raw_best(text) -> (category, confidence)`: melhor match BRUTO sobre todas as categorias, **sem** gate de threshold. Reusa o embedding (cache LRU → custo ~0); só um argmax a mais.
- `estixe/__init__.py`: após `classify()`, grava `risk_raw_category` + `risk_raw_confidence` no metadata (sempre que `risk_check_enabled`).
- `pipeline.py` (turn record): `TurnSummary.risk_score` = `risk_raw_confidence`; novo campo `TurnSummary.risk_category` = `risk_raw_category`.

## Parte B — Baseline por-categoria

- `risk_taxonomy.yaml`: novo campo `benign_ceiling` por categoria, semeado dos "max benigno" documentados:
  instruction_override 0.558 · privilege_escalation 0.444 · third_party_data_access 0.617 ·
  fraud_enablement 0.602 · policy_disclosure 0.696 · unsafe_transformation 0.503 ·
  ambiguous_high_risk + social_engineering → derivados do corpus real (não documentados).
- `RiskDefinition`: `+ benign_ceiling: float`.
- `aion/estixe/suspicion.py`:
  - `SuspicionParams` ganha `baselines: dict[str,float]` (mapa por-categoria) mantendo `baseline` (fallback global).
  - `update_suspicion(prev, risk, params, category=None)` resolve `baselines.get(category, params.baseline)`. `category=None` → global (backward-compat).
  - helper `baselines_from_taxonomy(risk_definitions) -> dict[str,float]`.
- `enforce_tightening` inalterado (opera sobre thresholds, não baseline).

## Calibração (re-derivada)

- `scripts/score_realtext_corpus.py`: passa a gravar `categories` paralelo a `risks` por caso.
- `suspicion_calibration_real.yaml`: cada caso ganha `categories: [...]`.
- `suspicion_eval`: `CalibrationCase` ganha `categories`; `detect_turn`/`score_grid_point` resolvem baseline por-categoria.
- `calibrate_suspicion.py`: baseline NÃO é mais grid — vem fixo da taxonomia; grid só sobre η/θ/detect_threshold.
- Aplica η/θ/threshold vencedores; baselines per-categoria ficam no YAML.

## Testes (TDD)

- `raw_best`: retorna top categoria+conf mesmo sub-threshold (requires_embeddings).
- `update_suspicion` per-categoria: baseline por categoria; fallback global; backward-compat (category=None).
- `baselines_from_taxonomy`: monta o mapa.
- Regressão: corpus real (com categorias) + defaults → FP-zero + recall ≥ alvo (esperado > 0.70).
- Re-roda smoke.

## Fronteiras / YAGNI

- Margem do baseline = 0 inicialmente (surpresa = raw − ceiling); se houver FP por variância, sobe via calibração/margem.
- NÃO mexe em enforcement (já feito) nem em NEMOS (P1.3).
- Parte A é correção de produção; vale mesmo que a Parte B não recupere todo o recall.

## Não-objetivos

- Baseline aprendido por-tenant via NEMOS (P1.3).
- η dependente de dados (P1.3).
