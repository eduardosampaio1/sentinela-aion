# Fase 6 — Clean Code ou Cemitério Futuro

## God files identificados

| Arquivo | Tamanho | Crime técnico | Consequência futura | Correção recomendada | Prioridade |
|---|---:|---|---|---|:---:|
| [aion/middleware.py](aion/middleware.py) | **~36 KB / 850+ linhas** | Hospeda: parsing de roles, RBAC, rate-limit local + Redis, audit trail + hash chain, validação de tenant, path-tenant cross-check, in-flight counter, audit log retrieval, chain tip cache, override storage. **Toda a "constituição" do produto em um só arquivo.** | qualquer mudança em RBAC arrisca quebrar audit; PR ficam impossíveis de revisar; testes ficam acoplados a setup gigante | quebrar em: `aion/security/auth.py` (parse_keys, _is_admin_path, _resolve_permission), `aion/security/tenant.py` (path_tenant, regex), `aion/security/rate_limit.py`, `aion/audit/chain.py` (HMAC + chain tip + Redis), `aion/audit/log.py` (deque + retrieval), `aion/middleware/security.py` (orchestrator). Rotas de override também devem migrar para `routers/`. | **S2** |
| [aion/pipeline.py](aion/pipeline.py) | **~22 KB** | Pipeline orchestrator + cache lookup + telemetria + módulos pre/post + emit_telemetry + módulo discovery — múltiplas responsabilidades | mudanças no semantic cache exigem entender pipeline; tests viram pesados | extrair `aion/pipeline/orchestrator.py` (run_pre/run_post), `aion/pipeline/telemetry_emitter.py`, `aion/pipeline/cache_layer.py` | S2 |
| [aion/proxy.py](aion/proxy.py) | **~15 KB** | HTTP client + circuit breaker + retry + provider URL mapping + format conversion (Anthropic) — 3 responsabilidades acopladas | adicionar provider novo é alto risco | extrair `aion/proxy/clients/{openai,anthropic,google}.py` + `aion/proxy/circuit_breaker.py` + `aion/proxy/retry.py` | S3 |
| [aion/main.py](aion/main.py) | **~12 KB** | lifespan + 3 background tasks inline + middleware register + CORS + exception handlers + routers register | crescimento contínuo | extrair `aion/lifecycle/{startup,shutdown,background_tasks}.py`; main.py vira shell | S3 |
| [aion/license.py](aion/license.py) | **~13 KB** | Validação JWT + state machine + abort UI + grace + premium feature gating | clear concerns; só faltam testes para todos os branches | manter; melhorar separação por classe | S4 |
| [aion/routers/intelligence.py](aion/routers/intelligence.py) | ~9 KB | Mistura overview, compliance summary, intents performance, threats — cada um é um produto separado | docs do `/v1/intelligence/*` ficam confusos | dividir em `routers/{intelligence_overview,compliance_summary,intents,threats}.py` | S3 |
| [aion/routers/observability.py](aion/routers/observability.py) | ~11 KB | health + metrics + stats + events + economics + cache + benchmark + tenant_metrics + models + version + recommendations + explain — **TUDO** | mudança em economia mexe em arquivo de health | quebrar por domínio | S3 |
| [aion/middleware.py:_extract_path_tenant](aion/middleware.py) | função | Lista hardcoded de prefixos `/v1/sessions/`, `/v1/intelligence/`, `/v1/threats/`, `/v1/data/` | ao adicionar `/v1/budget/{tenant}` ou `/v1/reports/{tenant}/...`, esquecer de adicionar aqui = vazamento entre tenants | mover para um decorator/dependency em FastAPI ou registrar lista única no router; fail-secure: rotas com `{tenant}` no path **devem** fazer cross-check sem opt-in | **S1** (já listado em SEC) |

## Duplicidade / divergência

- `cost_saved` é calculado em pelo menos 2 lugares: counter em `telemetry.py` e fallback em `intelligence.py:108`. Mantém risco de números diferentes em dashboards distintos.
- Métrica de "tokens_saved" aparece em counters globais e em `event.data` — não vi reconciliação garantida.
- "block_reason" / "detected_risk_category" usados intercambiavelmente em `intelligence.py:60-61` (`block_reasons = [(e.metadata).block_reason or detected_risk_category ...]`) — duplicidade semântica.

## Duplicação de domínio com `aion-console/`

- Console reimplementa tipos/dashboards baseado em endpoints do AION; sem schema compartilhado (OpenAPI). Risk de drift FE↔BE — relacionado à fase de contratos.

## TODOs e workaround sem explicação

Não rodei grep TODO/FIXME exaustivo neste audit. Recomendar como follow-up:
```
grep -rn "TODO\|FIXME\|XXX\|HACK\|TBD" aion/ scripts/ tools/ docs/
```

## Resumo

Não há crimes catastróficos de clean code, mas `middleware.py` e `pipeline.py` estão no caminho de virar god files insustentáveis. Severidade dominante: **S2/S3** — não bloqueia produção, mas vira radioativo conforme o time crescer.
