# Plano de Execução para Sair do Inferno

## Bloco 1 — "Agora ou nada" (bloqueia cliente enterprise)

| Item | ID | Severidade | Esforço (S/M/L/XL) |
|------|---|:---:|:---:|
| RBAC ownership operator↔tenant (claim no JWT do ator + tabela de mapeamento) | F-01, F-02, F-13 | S1 | **L** |
| `AION_PROFILE=production` que torna obrigatórios: `AION_SESSION_AUDIT_SECRET`, `AION_LICENSE_PUBLIC_KEY` (não-fallback), `AION_ADMIN_KEY` setada com formato `:role`, `AION_REQUIRE_TENANT=true`, `AION_REQUIRE_CHAT_AUTH=true`, rejeição de `AION_LICENSE_SKIP_VALIDATION=true` | F-03, F-04, F-05, F-11, F-12 | S1 | **M** |
| Sanitização de `event.data["input"]` (hash + length + intent) antes de `emit()` e antes de qualquer forwarding/storage | F-06 | S1 | **S** |
| Persistir `cost_saved_total` e contadores executivos (Redis ou time-series) com janela rastreável; usar NEMOS como fonte única de truth para `/v1/economics`, `/v1/intelligence` | F-07 | S1 | **M** |
| `total_spend_usd` retornar `null`/`0.0` quando histórico vazio; nunca usar `cost_saved` como fallback rotulado | F-08 | S2 | **S** |
| `/v1/explain` ler de NEMOS/Redis store durável (com TTL ≥ retenção legal) | F-10 | S1 | **M** |
| Per-request cost cap (`per_request_max_cost_usd`) + cap em output tokens injetado na request | F-15, F-16 | S1/S2 | **M** |
| Emitir `audit_secret_rotated` + persistir em secret manager + dual-secret window | F-23 | S2 | **M** |
| Validar `X-Aion-Actor-Role` via JWT assinado pelo console (ou outra prova criptográfica) | F-13 | S1 | **L** |

## Bloco 2 — "Antes da POC"

| Item | ID | Severidade | Esforço |
|------|---|:---:|:---:|
| Schema YAML `models.yaml` com `pricing_source`, `pricing_observed_at`, fonte rastreável; CI semanal valida drift | F-09 | S2 | **S** |
| Mover `license_id`, `entitlement_valid_until`, `restricted_features` para `/version` (já protegido). `/health` minimal | F-14 | S2 | **S** |
| Telemetry event schema estendido: `environment`, `feature_version`, `policy_version`, `model_prompt_hash`, `prompt_template_hash` | F-33 | S2 | **M** |
| Lockfile (uv/pip-tools) commitado; CI verifica drift | F-24 | S3 | **S** |
| Documentação de segurança refeita: `aion/rbac.py` removido, `start.py` removido, `AION_ADMIN_KEY` formato `:role` documentado, "702 testes" corrigido para número real (ou explicação de parametrize) | F-17, F-18, F-19 | S2/S3 | **S** |
| Legacy admin keys (sem `:role`) rejeitadas; warning no boot se detectado | F-20 | S2 | **S** |
| Cache distribuído (Redis vector ou pgvector) para multi-replica | F-25 | S2 | **L** |
| `_TENANT_PATTERN` regex revisado + tests com payloads adversariais (`..`, NULL, unicode) | F-29 | S2 | **S** |
| Sanitizar `X-Aion-Actor-Reason` (limit de tamanho + strip control chars) | F-31 | S2 | **S** |
| Eval suite adversarial AI/LLM com regression baseline (50+ casos) | F-27 | S2 | **L** |
| `seed_sandbox.py` exige `AION_ALLOW_SEED=true`; refusal em production | F-28 | S2 | **S** |

## Bloco 3 — "Antes de produção"

| Item | ID | Severidade | Esforço |
|------|---|:---:|:---:|
| Behavior dial: implementar mapeamento real para parâmetros do LLM (`temperature`, `top_p`, etc.) ou reposicionar promessa como "Behavior Profile" | F-21 | S2 | **L** |
| Decision contract incluir `original_request_hash`, `modified_request_hash`, `compression_ratio`, `policy_version_applied` para replay completo | F-22 | S2 | **M** |
| Métricas Prometheus com `tenant=` label (cardinality controlada via `aion_decisions_total{tenant="..."}`) | F-26 | S2 | **M** |
| Latency em Prometheus histogram nativo (deque substituída por buckets) | F-35 | S3 | **S** |
| `_TRUSTED_PROXY_ROLES` documentado e centralizado em `aion/security/trusted_roles.py` | F-30 | S3 | **S** |
| `hmac.compare_digest` em comparação de chaves admin | F-32 | S3 | **S** |
| Pipeline split: `aion/security/`, `aion/audit/`, `aion/lifecycle/`, `aion/proxy/clients/...`, `aion/pipeline/orchestrator.py` (god files breakdown) | god-files | S2/S3 | **XL** |
| OpenAPI fonte da verdade compartilhada com `aion-console` (codegen TS types) | contratos | S3 | **L** |
| pip-audit + bandit semanal CI + lock diff PR-blocking | SEC | S3 | **S** |

## Estimativa total

- **Bloco 1 (Agora ou nada):** ~9 itens, ~6–10 dev-weeks (2 devs sêniores).
- **Bloco 2 (Antes da POC):** ~12 itens, ~4–6 dev-weeks adicionais.
- **Bloco 3 (Antes de produção):** ~9 itens, ~4–8 dev-weeks adicionais (incluindo refactor god files).

Total: ~14–24 dev-weeks (sem stress test de carga real, que adiciona ~2 semanas).

## Recomendação de roadmap

1. **Sprint 1 (2 sem):** F-03, F-04, F-05, F-11, F-12, F-06, F-08, F-20 — quick wins de configuração + sanitização. Produto sai do estado "default inseguro".
2. **Sprint 2-3 (4 sem):** F-01, F-02, F-13 — RBAC ownership + console SSO trust. Produto sai do estado "qualquer admin opera qualquer tenant".
3. **Sprint 4-5 (4 sem):** F-07, F-10, F-15, F-16, F-23 — durabilidade de métricas, explain, cost cap, secret rotation. Produto sai do estado "métrica volátil".
4. **Pré-POC**: Bloco 2 todo.
5. **Pré-produção**: Bloco 3.
