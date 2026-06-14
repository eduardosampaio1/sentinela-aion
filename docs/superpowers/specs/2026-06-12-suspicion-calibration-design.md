# Spec — Calibração do acumulador de suspeita (Titans P0)

**Data:** 2026-06-12
**Origem:** DISC/VAL Titans P0 (Fase 1 já implementada). Pré-requisito da Fase 2 (enforcement).
**Branch:** `fix/estixe-ptbr-injection`

## Objetivo

Calibrar os gates do acumulador de suspeita (`aion/estixe/suspicion.py`) —
`η`, `θ`, `baseline`, `detect_threshold` — contra um corpus rotulado de
trajetórias multi-turno, sob critério **FP-zero primeiro**, e travar o
resultado como teste de regressão.

`S_t = η·S_{t-1} + θ·max(0, risk_t − baseline)`

## Princípio âncora (o que torna o fixture honesto)

As trajetórias de **ataque** mantêm **todo turno < limiar de ação single-turn**
(`risk_check 0.78`, `block_min 0.82`). Caso contrário a camada single-turn já
bloquearia e não seria um slow-burn. O acumulador é calibrado para a **banda
0.3–0.75 que as outras camadas perdem**.

## Critério de otimização (decidido)

1. Restrição dura: **FPR == 0** nas sequências benignas.
2. Entre os que passam: **maximizar recall** de ataque.
3. Desempate: **menor turns-to-detect** médio.
4. Se nenhum combo atinge FP-zero → o harness **falha alto** (não escolhe combo
   ruim em silêncio); revisamos fixture/baseline.

## Componentes

### 1. Fixture — `tests/data/suspicion_calibration.yaml`
~20 ataque + ~20 benigno. Cada entrada: `{id, label: attack|benign, kind, risks: [float...], note}`.
- **Ataque (deve disparar):** rampa oscilante (`[0.2,0.5,0.3,0.55,0.4,0.6]`),
  creep linear lento (0.2→0.65 em ~8 turnos), platô-e-empurra, probe
  spike-retreat (`[0.6,0.2,0.6,0.2,0.65]`).
- **Benigno (NÃO pode disparar):** chatter baixo (0.05–0.2), spike legítimo
  isolado (`[0.1,0.65,0.1,0.05]`), moderado estável (~0.3), sessão longa benigna
  (15 turnos 0.1–0.25).
- Invariante de construção: nenhum turno de ataque ≥ 0.78.

### 2. Harness — `scripts/calibrate_suspicion.py` (offline; fora do hot-path)
- Grid: η∈{.7,.8,.85,.9,.95} × θ∈{.5,1,1.5,2} × baseline∈{.25,.3,.35,.4} ×
  detect_threshold∈{.4,.6,.8,1,1.5,2}.
- Para cada combo, roda cada trajetória pela função pura **real**
  `aion.estixe.suspicion.update_suspicion` (calibra o mesmo código de prod).
- Métricas por combo: `fpr` (benigno que cruza), `recall` (ataque que cruza),
  `mean_turns_to_detect` (nos ataques pegos).
- Seleção pelo critério acima. Emite `qa-evidence/aion-suspicion-calibration/RESULTS.md`
  (combo vencedor, recall/FPR, ataques que escaparam).

### 3. Aplicação (gate humano)
Após revisar o report, atualizo os defaults `threat_suspicion_*` em
`EstixeSettings`. Não é auto-escrita.

### 4. Regressão — `tests/test_suspicion_calibration.py`
Carrega o fixture, roda com os defaults vigentes, assert `fpr == 0` e
`recall ≥ alvo` (o recall atingido na calibração). Mudança futura de param que
quebre a calibração → falha CI.

## Fluxo de dados

```
fixture (trajetórias) → harness (grid via update_suspicion) → params vencedores
   → defaults EstixeSettings (gate humano) → teste de regressão trava (fixture+params)
```

## Testes (TDD)

- Loader do fixture + função de scoring do harness (dado combo+fixture →
  fpr/recall/turns corretos) — RED antes.
- Teste de regressão (fixture + defaults → FP-zero, recall ≥ alvo).

## Fronteiras (YAGNI)

- Grid discreto pequeno e explicável; sem otimizador sofisticado.
- Zero acoplamento a embeddings (trajetórias diretas de risk_score).
- Aplicação manual dos params após revisar o report.
- **Não** mexe em enforcement (Fase 2) — só detecção/calibração.

## Não-objetivos

- Síntese de texto via classificador real (P1 — caminho híbrido).
- Baseline per-tenant aprendido via NEMOS (P1).
- η dependente de dados (P1).
