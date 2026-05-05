# Modo Executor — Prompts de Correção (top 6)

Cada bloco é um prompt independente para uma sessão de implementação focada.

---

## Fix #1 — RBAC ownership operator↔tenant

**Objetivo:** impedir que um operator com `data:delete` em sua chave consiga deletar/ler dados de outro tenant.

**Arquivos envolvidos:**
- `aion/middleware.py` (parsing de chaves; auth pipeline)
- `aion/shared/contracts.py` (Role + Permission)
- `aion/routers/data_mgmt.py`, `aion/routers/intelligence.py`, `aion/routers/budget.py`
- novo: `aion/security/ownership.py`

**Mudança esperada:**
1. Estender formato da chave para `key:role:tenant1,tenant2,...` (ou claim no JWT do ator quando trusted_proxy).
2. Em `_parse_key_roles`, retornar dict `{key: {role, tenants: set}}`.
3. Em todo handler com `{tenant}` no path: middleware verifica `path_tenant ∈ tenants(caller_key)` ou rejeita 403.
4. Para `console_proxy`, exigir JWT assinado pelo console com claims `role`, `tenants`. Validar assinatura em `aion/security/console_jwt.py`.

**Riscos:**
- Backwards-compat com chaves antigas. Solução: log warning e tratar legacy como `tenants=*` apenas durante 1 release minor.
- Performance: lookup é dict, ok.

**Testes obrigatórios:**
- 2 tenants A, B; key A_op `data:delete` só A → DELETE /v1/data/B → 403 + audit `tenant_ownership_violation`.
- key admin com `tenants=*` → mantém comportamento atual.
- Console proxy sem JWT → fallback VIEWER; com JWT inválido → 401.

**Eventos analíticos obrigatórios:**
- `event_type=tenant_ownership_violation` com `caller_key_fingerprint`, `requested_tenant`, `path`.

**Métricas afetadas:**
- novo Prometheus counter `aion_tenant_ownership_violation_total`.

**Critério de aceite:** suite verde + 5 cenários novos passando.

**Comando de validação:** `pytest tests/test_rbac_ownership.py -v`.

---

## Fix #2 — `AION_PROFILE=production` (modo seguro by default)

**Objetivo:** transformar deploy em produção em "fail-secure" — todos os warnings críticos viram bloqueios.

**Arquivos envolvidos:**
- `aion/config.py` (novo enum `Profile`)
- `aion/main.py` lifespan (boot validation)
- `aion/license.py` (rejeitar SKIP_VALIDATION em production)
- `aion/middleware.py` (rejeitar legacy keys em production)
- `docs/PRODUCTION_CHECKLIST.md` atualizar

**Mudança esperada:**
- `class Profile(str, Enum): development="development"; staging="staging"; production="production"`.
- `settings.profile = "development"` default; via `AION_PROFILE`.
- Em `lifespan`, se `profile == production`:
  - `AION_SESSION_AUDIT_SECRET` mandatório (atualmente warning).
  - `AION_LICENSE_PUBLIC_KEY` deve estar setado (não usar embedded).
  - `AION_LICENSE_SKIP_VALIDATION` rejeitado (sys.exit).
  - `AION_REQUIRE_TENANT=true`, `AION_REQUIRE_CHAT_AUTH=true` exigidos.
  - `AION_ADMIN_KEY` exigido com formato `:role`.
- Build Docker `production`: `AION_PROFILE=production` baked-in via build-arg.

**Testes:**
- `AION_PROFILE=production` sem secret → exit 1.
- `AION_PROFILE=production` com `AION_LICENSE_SKIP_VALIDATION=true` → exit 1.
- `AION_PROFILE=development` mantém comportamento atual.

**Critério de aceite:** boot logs explícito com profile em uso; banner de seguranças validadas.

---

## Fix #3 — Sanitização de PII em `event.data["input"]`

**Objetivo:** garantir que mensagens do usuário não vazem para `/v1/events`, `/v1/explain` ou ARGOS.

**Arquivos envolvidos:**
- `aion/shared/telemetry.py` (TelemetryEvent + emit)
- `aion/estixe/guardrails.py` (PII detector reusável)

**Mudança esperada:**
- Novo `_sanitize_input(text: str, pii_findings: list) -> dict`:
  - retorna `{"input_hash": sha256, "input_length": int, "input_intent": str, "input_redacted": redacted_text or None}`.
  - **nunca** persiste o texto original.
- `TelemetryEvent.__init__` recebe `input_text` mas só armazena o resultado sanitizado em `self.data["input"]` (dict, não string).
- Schema bump: `schema_version: "1.1"` para sinalizar mudança.
- Console e qualquer downstream lê `data["input"]["input_hash"]`.

**Riscos:**
- Quebra contrato com dashboards que liam `event.data.input` como string.
- Migração: durante 1 release, manter dual: `input_string` (deprecado) + `input` (novo dict). Após N releases, remover.

**Testes:**
- emit event com mensagem contendo CPF → assert `input_string` não existe; `input.input_hash` é sha256; `input.input_redacted is None`.
- ARGOS forwarder: capturar request body em mock — sem texto cru.

**Critério de aceite:** `grep -rE "input.*=" telemetry.py` não tem `input_text` cru no event.data.

---

## Fix #4 — Persistir métricas executivas (cost_saved, tokens_saved) em store durável

**Objetivo:** `/v1/economics` e `/v1/intelligence` mostram histórico contínuo, não "since last restart".

**Arquivos envolvidos:**
- `aion/shared/telemetry.py` (counters)
- `aion/nemos/__init__.py` (já persiste — usar como fonte)
- `aion/routers/observability.py` (`/v1/economics`)
- `aion/routers/intelligence.py` (`/v1/intelligence/{tenant}/overview`)

**Mudança esperada:**
- Cada `emit` que atualiza counter persiste delta em Redis hash `aion:counters:{tenant}` com TTL longa (90 dias).
- `/v1/economics` lê de Redis (fallback in-memory para testes).
- `total_spend_usd` retorna `0.0` ou `null` se histórico vazio (nunca `cost_saved` como fallback).

**Testes:**
- emit 10 events → reiniciar processo → `/v1/economics` retorna mesma soma.
- NEMOS sem dados → `total_spend_usd == 0.0`.

**Critério de aceite:** restart docker → counter mantido.

---

## Fix #5 — `/v1/explain` durável

**Objetivo:** auditor consegue explicar request de 30 dias atrás.

**Arquivos envolvidos:**
- `aion/routers/observability.py` (`/v1/explain/{request_id}`)
- `aion/shared/telemetry.py` (emit + Redis stream)
- novo: `aion/storage/explain_store.py`

**Mudança esperada:**
- A cada `emit`, gravar entrada `aion:explain:{request_id}` em Redis com TTL = `AION_TELEMETRY_RETENTION_HOURS` (default 7 dias; aumentar para 90+ em produção).
- Conteúdo: `decision`, `model_used`, `tokens_saved`, `cost_saved`, `latency_ms`, `metadata` (sanitizado), `timestamp ISO`, `tenant`, `module_chain`.
- `/v1/explain` busca primeiro Redis, depois buffer in-memory (fallback).
- Se `Supabase` configurado, write paralelo (já existe).

**Testes:**
- emit 1.500 events → buffer rola → explain do 1º em Redis ainda funciona.
- Redis off → `found:false` com mensagem "explain store unavailable".

---

## Fix #6 — Per-request cost cap + max_output_tokens cap

**Objetivo:** evitar que uma única request consuma o budget mensal e/ou estoure RAM no streaming.

**Arquivos envolvidos:**
- `aion/shared/budget.py` (`BudgetConfig`, `check_budget`)
- `aion/routers/proxy.py` (forward / stream)
- `aion/nomos/cost.py`

**Mudança esperada:**
- `BudgetConfig` ganha `per_request_max_cost_usd: Optional[float]`.
- Antes do `forward_request`, estimar custo: `prompt_cost = nomos.estimate_request_cost(model, prompt_tokens, max_tokens)`.
- Se `prompt_cost > per_request_max_cost_usd` → 402 com `error.code="per_request_cost_exceeded"`.
- Injetar `max_tokens=min(client_max, model_default_max, computed_cap)` antes de proxy.
- Em streaming, abort se `len(buffered_chunks) > N` (configurável `AION_STREAM_MAX_CHUNKS=10000`).

**Testes:**
- Tenant cap `per_request_max_cost_usd=0.01`; request grande → 402.
- Streaming mock que gera 100k chunks → request abort com erro estruturado.

**Critério de aceite:** chaos test gera output gigante, AION não OOM.
