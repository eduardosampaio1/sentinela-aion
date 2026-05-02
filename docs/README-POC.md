# AION — POC em 5 minutos

Dois modos POC, um stack docker-compose cada. Decisão é do cliente.

| Modo | Quando usar | Cliente expõe credencial LLM ao AION? |
|---|---|:---:|
| **Decision-Only** | banco / telecom / CISO restritivo / primeiro contato enterprise | **Não** |
| **Transparent** | integração acelerada, cliente flexível, "zero code change" | Sim |

Se a dúvida for genuína: comece pelo **Decision-Only**. Sempre dá pra evoluir.

---

## POC Decision-Only — setup

```bash
# 1. Variáveis de ambiente
cp .env.poc-decision.example .env
# Edite .env e preencha (todos obrigatórios):
#   AION_LICENSE                    JWT da Baluarte
#   AION_ADMIN_KEY                  chave humana — formato "minhakey:admin"
#   AION_CONSOLE_PROXY_KEY          openssl rand -hex 24
#   AION_SESSION_AUDIT_SECRET       openssl rand -hex 32
#   CONSOLE_AUTH_SECRET             openssl rand -hex 32

# 2. Subir
docker compose -f docker-compose.poc-decision.yml up -d

# 3. Smoke test (sem chamar LLM — Decision-Only)
curl -s http://localhost:8080/v1/decide \
  -H "Content-Type: application/json" \
  -H "X-Aion-Tenant: poc" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Olá"}]}' | jq .
# → {"decision":"bypass","bypass_response":"Olá! ...","latency_ms":1.x}

# 4. Tentar Transparent neste modo retorna 403 (F-37):
curl -s -o /dev/null -w "%{http_code}\n" \
  http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Olá"}]}'
# → 403  (decision_only_mode_violation)

# 5. Console (interface web)
# http://localhost:3000  → fazer login com SSO (configure GOOGLE / ENTRA no .env do console)
```

**O que esse setup garante:**
- AION nunca chama o LLM (`AION_MODE=poc_decision` + F-37 enforcement de runtime).
- AION nunca recebe credencial de LLM (compose não declara `OPENAI_API_KEY` etc.).
- Audit trail HMAC-assinado (F-03 — `AION_SESSION_AUDIT_SECRET` obrigatório).
- Console autenticado contra o backend (F-12 — `AION_CONSOLE_PROXY_KEY:console_proxy`).
- Console com sessão segura (sem fallback `insecure-default-change-in-prod`).
- `AION_PROFILE=staging` por padrão — boot loga critical em qualquer gap; suba com `AION_PROFILE=production` para hard-abort.

---

## POC Transparent — setup

```bash
# 1. Variáveis de ambiente
cp .env.poc-transparent.example .env
# Edite .env e preencha (todos obrigatórios):
#   AION_LICENSE                    JWT da Baluarte
#   AION_ADMIN_KEY                  formato "minhakey:admin"
#   AION_SESSION_AUDIT_SECRET       openssl rand -hex 32
#   OPENAI_API_KEY (ou ANTHROPIC_API_KEY etc.)
#
# Opcional: AION_CONSOLE_PROXY_KEY (se for rodar console separado)

# 2. Subir
docker compose -f docker-compose.poc-transparent.yml up -d

# 3. Smoke test (AION proxia para o LLM real)
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Aion-Tenant: poc" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Diga oi"}]}' | jq .

# 4. Configurar budget cap (F-16/F-36 exigem para evitar runaway de fatura)
curl -s -X PUT http://localhost:8080/v1/budget/poc \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <AION_ADMIN_KEY-sem-:admin>" \
  -d '{"daily_cap":10.0,"per_request_max_cost_usd":0.5,"on_cap_reached":"block"}'
```

**O que esse setup garante:**
- Audit trail HMAC-assinado (F-03).
- `AION_BUDGET_ENABLED=true` mandatório (F-36) — sem cap, qualquer bug vira fatura.
- F-12 ativa: chat 401 se chave admin não conferir.
- Streaming com cap de buffer (F-15) — abort estruturado em runaway de tokens.
- `AION_PROFILE=staging` por padrão.

---

## Solução de problemas comuns

| Sintoma | Causa | Fix |
|---|---|---|
| Console retorna 401 ao operar | `AION_CONSOLE_PROXY_KEY` ausente ou diferente nos dois lados | Garantir que está em `.env` E que aparece no `AION_ADMIN_KEY` do backend como `:console_proxy` |
| Compose recusa subir o console: `CONSOLE_AUTH_SECRET is required` | F-19 — fallback inseguro removido | Setar `CONSOLE_AUTH_SECRET` em `.env` (`openssl rand -hex 32`) |
| Boot loga warnings de auth/license/secret e não aborta | `AION_PROFILE=staging` (default) — só registra, não bloqueia | Production-ready: `AION_PROFILE=production` no `.env` (boot vai abortar se faltar algo) |
| `/v1/chat/completions` retorna 403 em POC Decision | F-37 funcionando como deveria | Use `/v1/decide` ou `/v1/decisions` |
| `cost_saved` no `/v1/economics` zera após restart | Redis não está conectado — F-07 cai em fallback in-memory | Garantir `redis` healthy no compose |
| `/v1/explain/{id}` retorna `found:false` em request recente | Redis indisponível ou TTL `AION_TELEMETRY_RETENTION_HOURS` baixo | Confirmar Redis + ajustar retention |

---

## Diferenças Decision-Only vs Transparent (rápido)

| | Decision-Only | Transparent |
|---|---|---|
| Endpoint principal | `POST /v1/decide` | `POST /v1/chat/completions` |
| AION chama LLM | ❌ Não (403 enforçado) | ✅ Sim |
| Cliente expõe credencial LLM | ❌ | ✅ |
| Budget cap obrigatório no boot | N/A (cliente paga direto) | ✅ (F-36) |
| Streaming guard | N/A | ✅ (F-15) |
| Decision contract com hashes (replay) | ✅ (é o produto) | ✅ |

---

## Próximos passos sugeridos depois da POC

1. Migrar `AION_PROFILE=staging` → `production` no `.env` quando todas as envs estiverem populadas.
2. Substituir `AION_LICENSE_PUBLIC_KEY` (env) pela chave Ed25519 oficial do cliente — fora do fallback embutido (F-04).
3. Configurar `AION_CORS_ORIGINS` para apenas as origens conhecidas do cliente.
4. Rodar `pytest tests/` em staging do cliente — a suíte cobre 791+ test cases.
5. Verificar coverage do integrity manifest (`aion/trust_guard/integrity_manifest.json`) para o conjunto de arquivos sensíveis do cliente.

Para detalhes operacionais full prod: [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md).
