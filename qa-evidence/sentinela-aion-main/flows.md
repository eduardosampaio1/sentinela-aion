# Fase 3 — Fluxos de Verdade

19 critérios por fluxo principal. Apenas os fluxos centrais auditados.

| # | Fluxo | Status | Evidência | Falha encontrada | Bloqueia? |
|---|---|---|---|---|:---:|
| F-1 | Pipeline `chat/completions` (Transparent): cliente → ESTIXE → NOMOS → METIS pre → LLM upstream → METIS post → resposta | **REAL COM RISCO** | [pipeline.py:233-415](aion/pipeline.py), [routers/proxy.py:354-645](aion/routers/proxy.py); testes em test_e2e, test_pipeline | streaming buffer-accumulate-flush sem cap explícito de output tokens; behavior dial atua via prompt injection (não param); decision_contract não cobre `modified_request` | S2 |
| F-2 | `/v1/decide` (Decision-Only): cliente → ESTIXE → response (template) ou CONTINUE | **REAL E VALIDADO** | [routers/proxy.py:286-351](aion/routers/proxy.py); test_decision_contract.py | bypass_response_text vem do YAML — comportamento por design, mas requer transparência cliente-facing | — |
| F-3 | License validation no boot: lê JWT → verifica Ed25519 → state ACTIVE/GRACE/EXPIRED/INVALID | **REAL COM RISCO** | [license.py:225-269](aion/license.py); test_trust_guard.py | (a) `AION_LICENSE_SKIP_VALIDATION=true` bypassa tudo; (b) chave pública fallback é dev (`MCowBQYDK2VwAyEAhh...`) — sem mecanismo que impeça produção sem override | S1 |
| F-4 | LGPD deletion `/v1/data/{tenant}` | **PARCIAL** | [routers/data_mgmt.py:25-60](aion/routers/data_mgmt.py); test_enterprise.py | path_tenant cross-check ✓; **mas RBAC não amarra operator a tenant** — admin de A apaga dados de B trocando header e URL | S1 |
| F-5 | Trilha de auditoria hash-chained | **REAL COM RISCO** | [middleware.py:362-442](aion/middleware.py); test_audit_a*.py | sem `AION_SESSION_AUDIT_SECRET`, vira SHA-256 sem HMAC — chain forjável; rotação de secret via `/v1/admin/rotate-keys` invalida continuidade do chain antigo | S1 |
| F-6 | Budget enforcement (cap por tenant) | **REAL E VALIDADO** | [shared/budget.py:184-226](aion/shared/budget.py); test_budget.py:52-72 | enforcement BEFORE LLM call ✓; falta per-request cap (S2); fallback in-memory se Redis off pode permitir double-spend cross-replica brevemente | S2 |
| F-7 | Tenant isolation (`X-Aion-Tenant`) | **REAL COM RISCO** | [middleware.py:583-703](aion/middleware.py); test_enterprise.py:89-132 | path_tenant cross-check para `/v1/sessions/`, `/v1/intelligence/`, `/v1/threats/`, `/v1/data/` ✓; mas com `require_tenant=false` (default), bucket "default" colide múltiplos clientes | S1 |
| F-8 | PII detection + masking (input) | **REAL E VALIDADO** | [shared/contracts.py:20-35](aion/shared/contracts.py); test_pii_policy.py | actions `ALLOW`/`MASK`/`BLOCK`/`AUDIT` enforçadas; cobertura razoável | — |
| F-9 | Output guard (PII após LLM) | **REAL** | [estixe/__init__.py:438-448](aion/estixe/__init__.py) | streaming acumula → checka full_text → flush; risco se buffer overflow | S2 |
| F-10 | Telemetria + ARGOS forwarding | **PARCIAL** | [shared/telemetry.py:124-197](aion/shared/telemetry.py) | `event.data["input"]` carrega texto cru do usuário; quando ARGOS opt-in ligado, **mensagem do usuário sai do ambiente** — viola promessa "respostas/prompts NUNCA saem" | S1 |
| F-11 | Supabase metadata writer | **REAL E VALIDADO** | [supabase_writer.py:78-160](aion/supabase_writer.py) | só metadata; circuit breaker fail-and-forget; chave em memória | — |
| F-12 | Behavior dial `PUT /v1/behavior` | **PARCIAL** | [metis/behavior.py:113-150](aion/metis/behavior.py) | promete "controle paramétrico em tempo real" mas atua principalmente injetando instruções no system prompt + cost_target → NOMOS; não controla `temperature`, `top_p` direto | S2 |
| F-13 | Circuit breaker upstream LLM | **REAL E VALIDADO** | [proxy.py:41-164](aion/proxy.py); chaos tests | threshold + recovery + Redis cross-replica ✓ | — |
| F-14 | Retry com exp backoff | **REAL E VALIDADO** | [proxy.py:273-345](aion/proxy.py) | bounded `max_retries=3`; retryable codes 429/500/502/503/504 | — |
| F-15 | Cache semântico per-tenant | **REAL COM RISCO** | [cache/__init__.py:55-276](aion/cache/__init__.py) | tenant scoping ✓; mas cache local LRU (não distribuído) — multi-replica perde hits ao trocar pod; multi-turn pode regredir | S2 |
| F-16 | Hot-reload intents/policies (`POST /v1/estixe/{intents,policies}/reload`) | **REAL** | [estixe/__init__.py:141-166](aion/estixe/__init__.py) | gated por RBAC `estixe:write`; ok | — |
| F-17 | Console SSO → AION (`X-Aion-Actor-Role`) | **PARCIAL / NÃO VALIDÁVEL NESTE AUDIT** | [middleware.py:727-740](aion/middleware.py) | aceita header de role sem validar SSO upstream — chave `console_proxy` é "trusted" e pode passar qualquer role; gap depende da configuração do console | S1 |
| F-18 | `/v1/explain/{request_id}` | **FUNCIONA MAS NÃO PROVA VALOR** | [observability.py:424-447](aion/routers/observability.py) | depende do buffer in-memory; "Request not found" frequente em produção | S1 |
| F-19 | `/v1/admin/rotate-keys` | **REAL COM RISCO** | [data_mgmt.py:63-88](aion/routers/data_mgmt.py) | rotação process-local; multi-replica desincronizado; nova HMAC quebra continuidade do chain antigo | S2 |
| F-20 | Trust Guard heartbeat + integrity | **REAL** | [main.py:184-196](aion/main.py); trust_guard/ | startup_validation + loop async; integrity manifest assinado no GHA via cosign; ok | — |
| F-21 | Approvals fluxo (timeout sweep) | **REAL** | [main.py:50-85](aion/main.py) | sweep a cada 60s, on_timeout=block default; ok | — |
| F-22 | Snapshot baselines NEMOS | **REAL** | [main.py:39-47](aion/main.py) | hourly; ok | — |
| F-23 | Cost saving "estimado_without_aion" | **MEDE MAS NÃO PROVA VALOR** | [intelligence.py:42-50](aion/routers/intelligence.py) | depende de preços hardcoded em models.yaml + counters voláteis; sem rastreabilidade da fonte | S1 |

## Bloqueios para produção

- **F-3 (S1):** `AION_LICENSE_SKIP_VALIDATION=true` mata todo o sistema de licenciamento. Fix: build de produção rejeita compile-time se essa env estiver setada.
- **F-3 (S1):** chave pública dev embutida — fix: build production requer `AION_LICENSE_PUBLIC_KEY` setado, valida fingerprint conhecido.
- **F-4 (S1):** ownership operator↔tenant não validado — fix: claim `tenant_id` no JWT do ator OU tabela `operator_tenants` e checagem antes de toda mutação destrutiva por tenant.
- **F-5 (S1):** `AION_SESSION_AUDIT_SECRET` deve ser obrigatório quando AION_PROFILE=production (que precisa existir).
- **F-7 (S1):** `AION_REQUIRE_TENANT=true` deve ser default produção.
- **F-10 (S1):** sanitizar `event.data["input"]`.
- **F-17 (S1):** validar `X-Aion-Actor-Role` via JWT assinado pelo console (não confiar em header puro).
- **F-18 (S1):** `/v1/explain` precisa ler de NEMOS/Redis ou store persistente.
- **F-23 (S1):** `cost_saved_total` precisa de persistência durável; baseline de preços precisa fonte/timestamp.
