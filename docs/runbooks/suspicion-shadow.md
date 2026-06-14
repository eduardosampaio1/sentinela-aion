# Runbook — Shadow do Acumulador de Suspeita (antes de ligar enforce)

Objetivo: confirmar **FP-zero no tráfego real de UM tenant** antes de ligar a Fase 2
(`ESTIXE_THREAT_ENFORCE_ENABLED=true`). A Fase 1 (detecção) já roda em observe-only.

## Pré-condições

- `AION_MULTI_TURN_CONTEXT=true` e `REDIS_URL` configurado (suspeita persiste no Redis por sessão).
- `ESTIXE_THREAT_ENFORCE_ENABLED=false` (observe-only — default).
- Clientes enviando `X-Aion-Session-Id` estável por conversa (senão o session_id é derivado por hash da 1ª msg).

## Passo a passo

1. **Ligar observação** (já é o default): a cada turno o pipeline grava `suspicion` no
   `TurnContext` (Redis `aion:session_ctx:{tenant}:{session}`) e emite `accumulated_pressure`
   no `ThreatStore` (Redis `aion:threat:{tenant}:{session}`, TTL 24h) quando cruza o detect_threshold.
2. **Rodar N dias** de tráfego real do tenant (sugerido: ≥ 7 dias ou ≥ 1000 conversas multi-turn).
3. **Analisar** com `python scripts/shadow_report.py --base <url> --admin <key> --tenant <t>`:
   - Lista os sinais `accumulated_pressure` ativos do tenant (via `GET /v1/threats/{tenant}`).
   - Para cada sinal, inspecionar a sessão: foi ataque real ou conversa legítima?
   - **Critério de aprovação: ZERO sinal sobre conversa legítima** (FP real = 0).
4. **Se houver FP** (sinal sobre conversa legítima): NÃO ligar enforce. Subir o
   `benign_ceiling` da(s) categoria(s) culpada(s) em `risk_taxonomy.yaml::suspicion_baselines`
   (+ o turno benigno que disparou ao corpus `suspicion_realtext_corpus.yaml`), recalibrar
   (`scripts/calibrate_suspicion.py`) e repetir o shadow.
5. **Se FP-zero confirmado**: ligar `ESTIXE_THREAT_ENFORCE_ENABLED=true` **por instância**
   (single-tenant on-prem). Começar com enforce só apertando threshold (nunca block direto).
   Monitorar `suspicion_enforced` no `/v1/explain` + taxa de aperto.

## Notas

- enforce_threshold=0.5 calibrado pra escala per-categoria (detect=0.1). Ajustar por tenant
  via `PUT /v1/overrides` se o tráfego do tenant exigir.
- Lembrar do teto: detecção por-score só separa bem a família jailbreak/override. Privilege/
  fraude/acesso/social não são separáveis por score (P1.3, sinal comportamental).
- Evidência do plumbing E2E: `qa-evidence/aion-suspicion-shadow/RESULTS.md`.
- Validação ao vivo de role-aware + enforcement: `qa-evidence/aion-suspicion-shadow/LIVE-ROLE-ENFORCE.md`.
- **Cache de decisão**: conteúdo idêntico repetido short-circuita (raw=0, sem re-classificar). Tráfego real é variado, mas a análise do shadow não deve assumir re-classificação em conteúdo repetido.
- **Role (P1.3)**: o app integrador deve enviar `X-Aion-User-Role` (server-side) pra isentar admins/support legítimos. Sem isso, admin legítimo acumula suspeita em privilege/third_party (e, com enforce on, sofre aperto).
