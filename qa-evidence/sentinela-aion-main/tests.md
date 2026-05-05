# Fase 5 — Testes Que Prestam ou Teatro

## Contagem real

```
$ grep -rch "^\(async \)\?def test_" tests/  # somando todos os arquivos
201
```

- Arquivos de teste: **50** (`tests/*.py`).
- Funções `def test_*`: **201** (com agentes/Bash; o `qa-porteiro` Agent reportou 605 — provável diferença é que aquele comando contou outro padrão; **a contagem direta auditável é 201**).
- **Doc claim:** "702+ testes" ([PRODUCTION_CHECKLIST.md:109](docs/PRODUCTION_CHECKLIST.md), [:130](docs/PRODUCTION_CHECKLIST.md)).

A diferença pode ser explicada se cada `test_*` for parametrizado com média de 3,5 cases. Mas a documentação **não qualifica isso** — ver L-1 em `lies.md` (S2).

## Tabela de cobertura crítica

| Área | Teste atual | Problema | Teste necessário | Severidade |
|---|---|---|---|:---:|
| Tenant isolation (escrita) | test_enterprise.py — pipeline impede módulo de "hijack" tenant (concorrência 20 tenants) | ✅ cobre o **caso interno**; **não cobre** RBAC ownership cross-tenant via API admin | teste: operator do tenant A com `data:delete` chama `DELETE /v1/data/B` → deve receber 403 | **S1** (gap crítico) |
| Tenant isolation (leitura) | — | mesmo gap | teste: operator de A chama `GET /v1/intelligence/B/overview` → 403 | **S1** |
| License | test_trust_guard.py (~70 tests) — Ed25519, manifest, state transitions | ✅ cobre estados | falta teste: `AION_LICENSE_SKIP_VALIDATION=true` em prod **deveria recusar** (ainda não recusa) | S2 |
| License | — | falta | teste: chave pública não setada + JWT assinado pela chave dev embutida → ainda passa (e é o que queremos travar em prod) | S1 |
| Audit HMAC | test_audit_a*.py — chain integrity | ✅ cobre quando secret está setado; **não testa** cenário de secret ausente em modo "production" | teste: AION_PROFILE=production + secret ausente → boot deve abortar | S1 |
| Budget cap | test_budget.py:52-72 — BudgetExceededError raised before LLM call | ✅ ok | falta: teste de **per-request cap** (fluxo grande passa hoje) | S2 |
| PII redaction | test_pii_policy.py (15 tests) — MASK/ALLOW/BLOCK/AUDIT | ✅ ok input | falta teste: garantir que `event.data["input"]` é sanitizado antes do `emit()` (atualmente NÃO é) | S1 |
| Rate limit | conftest setup + middleware tests | ⚠ mas o fallback in-memory não é testado em modo multi-replica simulado | teste: 2 replicas, cada uma com seu deque → cliente excede 2x o limite por roundrobin DNS | S3 |
| Prompt injection | test_threat_detector.py (26 tests), test_poc_security.py | parcial — sem eval set adversarial estruturado com baseline | criar eval suite com 50 prompts adversariais (já existem em comunidade) e baseline FP/TP rate; CI quebra se regredir | S2 |
| Streaming buffer | test_chaos.py + test_safe_mode.py | provavelmente não testa OOM com output gigante | teste: mock upstream que stream 1M tokens → AION abort com erro estruturado, sem OOM | S2 |
| `/v1/explain` | test_e2e.py:188-192 (request_id em headers) | não testa "request fora do buffer" | teste: emit 1.500 events, depois explain o 1º → deve dar `found:false` documentado, não buscar em store persistente (porque store ainda não existe) | S1 |
| Cost saved metric | test_telemetry.py (3 tests) | não testa durabilidade pós-restart | teste: simular restart e validar que `cost_saved_total` NÃO zera (irá falhar hoje — confirma o bug) | S1 |
| Cross-tenant cache leak | test_cache.py | precisa confirmar que cache key inclui `tenant` em todos os paths | teste: tenant A pede prompt X, tenant B pede prompt X — não deve haver hit | S2 |
| ARGOS forwarding redaction | — | sem teste | teste: ligar argos_telemetry_url para mock; enviar mensagem com PII; assertar que body do POST não contém o PII | **S1** |
| Console SSO trusted-proxy | — | gap depende de teste e2e do console | teste: chave `console_proxy` válida + `X-Aion-Actor-Role: admin` sem SSO upstream → AION concede admin (atualmente sim — deveria ser não) | S1 |
| Idempotência | test_idempotency.py (não auditado em profundidade) | provável ok | — | — |
| Chaos | test_chaos.py — provavel cenários degradados | depende — não auditado em profundidade | — | — |
| Decision contract | test_decision_contract.py (38 tests) | ok para shape do contract | falta cobertura: `modified_request` ausente no contract → replay incompleto | S2 |
| Stress | test_stress.py (não rodado neste audit) | — | — | — |

## Classificação geral

| Tipo | Quantidade aproximada |
|:---:|---|
| **TESTE REAL** | ~70% (test_e2e, test_pipeline, test_enterprise, test_pii_policy, test_budget, test_trust_guard, test_audit_*) |
| **TESTE COSMÉTICO ou MOCK-HEAVY** | ~20% (test_bench_suite, test_telemetry simples, alguns test_schemas) |
| **MENTIROSO (passaria com regra quebrada)** | indeterminado sem rodar mutation testing |
| **AUSENTE** | gaps listados acima — **principalmente RBAC ownership por tenant, PII em telemetry, durability de métricas, console SSO trust** |

## Pontos positivos

- Boa cobertura de pipeline interno (test_enterprise concorrente).
- Trust Guard tem 70 testes — sólido.
- Audit a1..a8 cobrem chain integrity em vários cenários.
- Decision contract testado em 38 cenários.
- Tests para multi-turn integration (26).

## Gaps por severidade

| S | Itens |
|:---:|---|
| S1 | RBAC ownership cross-tenant; license skip rejection; PII no telemetry; ARGOS redaction; explain durability; cost_saved durability; console SSO trust |
| S2 | per-request cap; eval suite adversarial; streaming OOM; modified_request no contract; cross-tenant cache leak |
| S3 | rate limit cross-replica |

## Recomendação

CI **deve** rodar:

1. `pytest tests/` blocking merge (não vimos no workflow `.github/workflows/publish.yml` — somente build/sign de imagem; pode existir outro workflow não auditado).
2. `pip-audit` semanal + lock file diff.
3. Eval suite de prompts adversariais (50+ casos, baseline FP/TP).
4. Mutation testing pontual (ex: mutmut em `aion/middleware.py` para validar que tests detectam mudanças).
