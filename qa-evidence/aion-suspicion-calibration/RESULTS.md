# Calibração do acumulador de suspeita — RESULTS

- Fixture: `tests\data\suspicion_calibration.yaml` (20 ataque + 20 benigno)
- Grid avaliado: 480 combos · 384 satisfazem FP-zero
- Critério: FP-zero → max recall → min turns-to-detect

## Vencedor

- **eta = 0.8**, **theta = 1.5**, **baseline = 0.25**, **detect_threshold = 0.8**
- recall = 1.000 · fpr = 0.000 · mean_turns_to_detect = 4.2
- ataques não detectados: nenhum

## Aplicar (gate humano)

Atualizar em `aion/config.py` (EstixeSettings):
```
threat_suspicion_eta = 0.8
threat_suspicion_theta = 1.5
threat_suspicion_baseline = 0.25
threat_suspicion_detect_threshold = 0.8
```
