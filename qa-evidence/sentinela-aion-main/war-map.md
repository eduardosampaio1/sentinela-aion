# Fase 0 — Mapa de Guerra

## Tipo de projeto

- **Anchor primário**: Backend service / API standalone (FastAPI proxy OpenAI-compatible).
- **Anchor secundário**: ML/AI system (intercepta LLM, classificação por embeddings, behavior dial, model routing). **Sub-fase 4.1 (AI/LLM Risk Bundle) aplicável**.
- **Anchor terciário**: Frontend SPA Next.js (`aion-console/`).

## Stack

| Camada | Tecnologia | Versão (pin?) |
|---|---|---|
| Runtime backend | Python 3.10+ | minimum (`requires-python = ">=3.10"`) |
| Framework HTTP | FastAPI | `>=0.115.0` (não pinned) |
| Validação | Pydantic v2 + pydantic-settings | `>=2.10.0` / `>=2.6.0` |
| HTTP client | httpx | `>=0.27.0` |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | `>=3.0.0` |
| Vector store | faiss-cpu | `>=1.7.4` |
| Token count | tiktoken | `>=0.7.0` |
| Cache distribuído | redis (Upstash compatível) | `>=5.0.0` (opcional) |
| Crypto licença | PyJWT + cryptography (Ed25519) | `>=2.8.0` / `>=41.0.0` |
| Serv ASGI | uvicorn[standard] | `>=0.30.0` |
| Console | Next.js (TS) + NextAuth v5 | (lock file presente) |
| Telemetria opcional | Supabase (PostgREST), ARGOS HTTP forwarder | runtime |
| Build/Deploy | Docker (multi-stage) + cosign keyless (GHA) + GHCR | manifest assinado |

## Componentes principais

```
aion/
  __init__.py                  # version, package marker
  cli.py                       # entrypoint: `aion` CLI invoca uvicorn
  config.py                    # Settings (Pydantic) + dangerous defaults
  license.py                   # Ed25519 JWT validator + abort/grace/expired
  main.py                      # FastAPI app + lifespan + CORS + routers
  middleware.py                # AionSecurityMiddleware: auth, RBAC, rate-limit, audit, tenant validation
  observability.py             # OpenTelemetry setup (opt-in)
  pipeline.py                  # Pipeline orquestrador pre/post LLM
  proxy.py                     # forward_request → OpenAI/Anthropic/Google
  supabase_writer.py           # opt-in metadata writer (PostgREST)

  estixe/                      # Bypass classifier + policy + guardrails + threat detector + suggestions
  nomos/                       # Model registry, complexity classifier, cost calc, router
  metis/                       # Compressor, behavior dial, response optimizer
  nemos/                       # Economics tracker, IntentMemory, baselines, recommendations
  trust_guard/                 # Manifest integrity, license claims, entitlement engine, heartbeat
  contract/                    # DecisionContract pydantic models
  cache/                       # Semantic cache (FAISS-backed), per-tenant
  collective/                  # Editorial policy catalog (Phase 0: install lifecycle only, runtime NOT applied)
  marketplace/                 # (não auditado em profundidade)
  reports/                     # PDF generation (reportlab)
  routers/                     # FastAPI routers (proxy, observability, control_plane, budget, sessions, approvals, intelligence, reports, data_mgmt, global_feed, collective)
  shared/                      # contracts (Role/Permission/PiiAction), telemetry, budget store, session_audit, tokens

aion-console/                  # Next.js: páginas admin, budget, estixe, intelligence, operations, policies, reports, routing, sessions, settings, shadow
config/                        # YAML: models, policies, complexity_archetypes, rewrite_rules, services, pii_exclusions
docker/                        # Dockerfile.aion, Dockerfile.mock_llm, nginx.conf, prometheus.yml, alerts.yml, grafana-provisioning/
docs/                          # ARCHITECTURE, PRODUCTION_CHECKLIST, RUNBOOK, SECURITY_REPORT, integration-guide, poc-integration-guide, quickstart, roteiro-poc
tests/                         # 50 arquivos de teste
tools/                         # generate_license.py, generate_manifest.py, keys/{public.pem, .gitignore}
.github/workflows/             # publish.yml (GHCR + cosign + manifest)
```

## Entrypoints (HTTP)

| Tipo | Endpoint | Auth | Notas |
|---|---|---|---|
| Público | `GET /health` | — | expõe `license_id`, `entitlement_valid_until`, `restricted_features`, `auth_warnings`, `aion_mode` (reconhecimento gratuito) |
| Público | `GET /ready` | — | Kubernetes readiness |
| Público | `GET /metrics` | — | Prometheus scrape |
| Público | `GET /docs`, `/openapi.json`, `/redoc` | — | OpenAPI |
| Chat | `POST /v1/chat/completions` | opcional (`AION_REQUIRE_CHAT_AUTH`) | proxy transparente OpenAI-compatible |
| Chat | `POST /v1/decide` | opcional | decisão pura (não chama LLM) |
| Chat | `POST /v1/chat/assisted` | opcional | decisão + execução + contrato |
| Chat | `POST /v1/decisions` | opcional | só DecisionContract |
| Admin | `GET /v1/audit` | RBAC `audit:read` | trilha hash-chained |
| Admin | `DELETE /v1/data/{tenant}` | RBAC `data:delete` | LGPD; ver §11 (tenant ownership não validado) |
| Admin | `POST /v1/admin/rotate-keys` | RBAC | troca `AION_SESSION_AUDIT_SECRET` em memória do processo (não persiste; multi-replica fica desincronizado) |
| Admin | `PUT/DELETE /v1/killswitch` | RBAC | `AION_SAFE_MODE` |
| Admin | `GET/PUT/DELETE /v1/behavior` | RBAC | Behavior Dial |
| Admin | `GET/PUT/DELETE /v1/overrides` | RBAC | overrides por tenant |
| Admin | `PUT /v1/modules/{name}` | RBAC | toggle ESTIXE/NOMOS/METIS |
| Admin | `GET/PUT /v1/budget/{tenant}` | RBAC | cap diário/mensal |
| Admin | `POST /v1/estixe/intents/reload` | RBAC | hot-reload |
| Admin | `POST /v1/estixe/policies/reload` | RBAC | hot-reload |
| Intel | `GET /v1/intelligence/{tenant}/overview` | RBAC + tenant mismatch check | dashboard executivo |
| Intel | `GET /v1/intelligence/{tenant}/compliance-summary` | RBAC | CISO summary com signature opcional |
| Intel | `GET /v1/intelligence/{tenant}/intents` | RBAC | NEMOS IntentMemory |
| Intel | `GET /v1/threats/{tenant}` | RBAC | sinais multi-turno |
| Obs | `GET /v1/stats`, `/v1/events`, `/v1/economics`, `/v1/explain/{request_id}` | inferido público (não em `_ADMIN_PREFIXES`) | vide §16 |
| Obs | `GET /v1/cache/stats`, `/v1/benchmark/{tenant}`, `/v1/metrics/tenant/{tenant}`, `/v1/models`, `/v1/recommendations/{tenant}` | parcial | parcialmente protegido por path-tenant check |
| Mgmt | `GET /version` | RBAC operator | build/license info |
| Misc | `/v1/sessions/...`, `/v1/approvals/...`, `/v1/reports/...`, `/v1/global-feed/...`, `/v1/collective/...` | RBAC variado | suportes |

CLI: `aion` (entrypoint via `pyproject.toml [project.scripts]`) lança uvicorn em `:8080`.

## Dependências críticas
- **OpenAI / Anthropic / Google** (LLMs upstream).
- **Redis** (recomendado em produção para budget, rate-limit, audit chain, cache, behavior; tudo tem fallback in-memory).
- **Supabase** (opt-in para telemetria de metadados).
- **HuggingFace embedding model** (cacheado offline em prod via `HF_HUB_OFFLINE=1`).
- **ARGOS** (opt-in, opt-in DPA — telemetria externa Shadow Mode).

## Variáveis de ambiente — defaults perigosos

| Var | Default | Problema |
|---|---|---|
| `AION_REQUIRE_TENANT` | `false` | sem header → bucket "default" colide múltiplos clientes (S1) |
| `AION_REQUIRE_CHAT_AUTH` | `true` | mas sem `AION_ADMIN_KEY`, auth é silenciosamente desabilitada (S1) |
| `AION_ADMIN_KEY` | `""` | sem chave → auth admin pass-through em rotas não-críticas; `_CRITICAL_PERMISSIONS` fail-secure mas há gap (S1) |
| `AION_SESSION_AUDIT_SECRET` | `""` | sem secret → audit log usa SHA-256 simples (não HMAC), forjável (S1) |
| `AION_FAIL_MODE` | `open` | crash → request passa direto pro LLM sem proteção (decisão consciente, mas é S2 se não for explícito ao cliente) |
| `AION_LICENSE_PUBLIC_KEY` | embedded dev key | sem override em prod → qualquer licença emitida com chave dev (que está no histórico do repo + tools/keys/public.pem) é aceita (S1/S2) |
| `AION_LICENSE_SKIP_VALIDATION` | unset | `=true` desabilita TODA validação de licença, marca tenant como "dev" (S2 se acidentalmente em prod) |
| `cors_origins` | `""` | bom default (sem CORS); ok |
| `default_tenant` | `"default"` | combinado com `require_tenant=false` produz o bucket-único |

## Boundary de isolamento adotado

`tenant` = string em header `X-Aion-Tenant`, regex `_TENANT_PATTERN` (não vi o regex; precisa validação contra injection no nome).

**Path tenant cross-check existe** (`middleware.py:691-703`): para prefixos `/v1/sessions/`, `/v1/intelligence/`, `/v1/threats/`, `/v1/data/`, o tenant na URL deve **bater** com o do header — protege contra "header X-Aion-Tenant: A + URL /v1/data/B".

⚠ **Mas isso só ataca um vetor**: um operator com `data:delete` que passa header **e** URL para o tenant alvo (B) ainda passa. Não há **ownership check** ligando "qual tenant esse operator administra".

## Riscos a olho nu (a aprofundar nas fases seguintes)

| Área | Risco preliminar | Severidade hint |
|---|---|---|
| Multi-tenant isolation | Tenant ownership não atrelado ao operator | S1 |
| License | Chave pública dev embutida; bypass via env | S1/S2 |
| Audit HMAC | Opcional → forjável | S1 |
| Telemetria | `event.data["input"]` contém mensagem do usuário sem sanitização | S1 |
| Métricas executivas | `cost_saved_total` in-memory (zera no restart); preços hardcoded em models.yaml; fallback "savings = cost_saved" pode mostrar saving inflado quando NEMOS sem dados | S1/S2 |
| Streaming | buffer-accumulate-flush sem cap explícito de tokens de output | S2 |
| Decision contract | não inclui `modified_request` → reprodução incompleta | S2 |
| Behavior dial | mais "prompt injection" do que "controle paramétrico"; pode deixar promessa "Mude o comportamento sem deploy" parcialmente verdadeira | S2/S3 |
| Dependency pinning | tudo `>=`, sem lockfile no repo | S3 |
| Documentação | "702+ testes" enquanto grep direto retorna 201 funções `def test_` | S2 |
| Documentação | `aion/rbac.py` referenciado mas não existe | S3 |
| Documentação | `start.py` referenciado mas não existe | S3 |
