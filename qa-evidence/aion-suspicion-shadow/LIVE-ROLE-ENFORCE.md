# Validação ao vivo (prod local) — Role-aware (P1.3) + Enforcement (Fase 2)

Backend fonte :8095 + Redis docker + Ollama, `AION_MULTI_TURN_CONTEXT=true`,
**`ESTIXE_THREAT_ENFORCE_ENABLED=true`** (ninguém usando o AION → seguro ligar local).

## 1. Enforcement (Fase 2) — DISPARA ao vivo

Conversa de privilege acumulou suspeita; o log do backend registrou o aperto:
```
WARNING aion.estixe: Suspicion enforcement: tenant=live-test suspicion=0.941 -> thresholds tightened
WARNING aion.estixe: Suspicion enforcement: tenant=live-test suspicion=1.425 -> thresholds tightened
WARNING aion.estixe: Suspicion enforcement: tenant=live-test suspicion=1.076 -> thresholds tightened
```
→ suspeita ≥ enforce_threshold (0.5) aperta os thresholds do turno seguinte, end-to-end. **Fase 2 provada ao vivo.**

## 2. Role-aware (P1.3) — ISENTA ao vivo (teste controlado)

Mesmas mensagens de privilege (novas, sem cache), run com `X-Aion-User-Role: admin`:
```
ADMIN  raw: [0.762, 0.697, 0.677]  cats: privilege_escalation ×3  -> suspicion: 0.0
```
O classificador RODOU (scores reais ~0.7, que SEM role acumulariam — cf. run A abaixo), mas
o role=admin **isentou** privilege → suspeita 0.0. Comparar com run sem role:
```
NOROLE (run A inicial) raw: [0.842, 0.67, ...] -> suspicion: 0.753 + accumulated_pressure
```
Mesmo tipo de pedido, **identidade vira o resultado**: atacante comum acumula+sinaliza; admin legítimo isento.

## Aprendizado operacional (cache de decisão)

Conversas com conteúdo IDÊNTICO repetido batem no cache de decisão do ESTIXE → 2ª execução
short-circuita (raw=0). Por isso o teste controlado usa mensagens novas e roda o caso admin
primeiro. **Nota pro shadow real**: tráfego real é variado, mas a análise não deve assumir
re-classificação em conteúdo repetido.

## Limite confirmado ao vivo

Ambos os runs de privilege levaram **403 single-turn block** independente do role — o block
single-turn NÃO é role-aware (item separado). Role só afeta o acumulador multi-turn.
