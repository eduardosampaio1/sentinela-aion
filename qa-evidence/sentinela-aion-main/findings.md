# Achados Detalhados Consolidados

Cada achado segue o template do Ceifador. Sigla: `F-XX`. Severidade S0–S4.

---

### F-01 — Operator com `data:delete` apaga dados de qualquer tenant

- **Severidade:** S1
- **Área:** Segurança / Multi-tenant isolation
- **Arquivo:** [aion/routers/data_mgmt.py:25-60](aion/routers/data_mgmt.py); [aion/middleware.py:705-754](aion/middleware.py); [aion/middleware.py:583-703](aion/middleware.py)
- **Função/Endpoint:** `DELETE /v1/data/{tenant}` → `delete_tenant_data(tenant: str)`
- **O que está errado:** o handler aceita `tenant` na URL e executa deleção em behavior dial, telemetria, cache, suggestions, NEMOS. O middleware faz cross-check `path_tenant == header tenant`, mas **não há ownership check** ligando a chave de admin ao tenant que ela tem direito de operar. Operator do tenant A com permissão `data:delete` consegue setar `X-Aion-Tenant: B` e `DELETE /v1/data/B` — passa.
- **Evidência encontrada:** trecho do handler sem `request: Request` para validar caller, e middleware sem ownership map.
- **Impacto real:** LGPD violation cross-customer. Em deploy multi-tenant, um cliente pode (acidentalmente ou maliciosamente) apagar dados de outro.
- **Como reproduzir:** dois tenants `acme` e `globex`. Configurar `AION_ADMIN_KEY=key_acme:operator,key_globex:operator`. Com `key_acme`, enviar `DELETE /v1/data/globex` com `X-Aion-Tenant: globex`. AION executa.
- **Correção obrigatória:** introduzir tabela/claim `operator_tenants` com lista de tenants permitidos por chave; rejeitar 403 quando `path_tenant ∉ operator_tenants(caller_key)`. Para deploy single-tenant on-prem, declarar isso explicitamente.
- **Critério de aceite:** teste e2e: 2 tenants, key A com permissão `data:delete` no próprio tenant tenta DELETE no tenant B → 403 + audit entry `tenant_ownership_violation`.
- **Status:** **Reprovado**.

---

### F-02 — Operator lê insights de qualquer tenant via `/v1/intelligence/`

- **Severidade:** S1
- **Área:** Segurança / Multi-tenant
- **Arquivo:** [aion/routers/intelligence.py:20-261](aion/routers/intelligence.py)
- **Endpoints afetados:** `/v1/intelligence/{tenant}/overview`, `/compliance-summary`, `/intents`, `/threats/{tenant}`
- **O que está errado:** mesmo gap do F-01. RBAC checa `audit:read` mas não amarra `caller→tenant`.
- **Impacto real:** leak de "savings_usd", "block_reasons", "PII intercepts", "top_model_used" entre clientes.
- **Correção obrigatória:** mesma de F-01.
- **Status:** **Reprovado**.

---

### F-03 — `AION_SESSION_AUDIT_SECRET` opcional → audit chain forjável

- **Severidade:** S1
- **Área:** Auditoria
- **Arquivo:** [aion/middleware.py:362-369](aion/middleware.py); [aion/main.py:125-129](aion/main.py)
- **O que está errado:** quando `AION_SESSION_AUDIT_SECRET` não está definido, `_hash_entry` usa `hashlib.sha256(serialized)`. Sem chave secreta, qualquer um com acesso ao log pode recomputar entradas falsas. Boot só **avisa** (`_env_problems`) e só aborta se `AION_FAIL_MODE=closed` (que não é default).
- **Evidência:**
  ```python
  secret = os.environ.get("AION_SESSION_AUDIT_SECRET", "")
  if secret:
      return _hmac.new(secret.encode(), serialized.encode(), hashlib.sha256).hexdigest()
  return hashlib.sha256(serialized.encode()).hexdigest()  # forjável
  ```
- **Impacto real:** "tamper evidence theater" — texto literal do warning. Em incidente real (auditor regulador, dispute), o produto não pode provar integridade da trilha.
- **Correção obrigatória:** introduzir `AION_PROFILE` (development|production); em `production`, secret é mandatório → boot aborta. Documento de deploy explicita.
- **Critério de aceite:** boot com `AION_PROFILE=production` sem secret → exit 1 com mensagem clara.
- **Status:** **Reprovado**.

---

### F-04 — Chave pública Ed25519 dev embutida; sem enforcement de override em produção

- **Severidade:** S1
- **Área:** Licença / Trust
- **Arquivo:** [aion/license.py:38-42](aion/license.py)
- **O que está errado:** `_PUBLIC_KEY_PEM = os.environ.get("AION_LICENSE_PUBLIC_KEY", _EMBEDDED_PUBLIC_KEY)`. O fallback embutido é uma chave **dev/test** (comentário linha 36: "Replace with production key before shipping"). Sem mecanismo que **force** a troca, qualquer deploy que esquecer a env aceita licenças assinadas com a chave dev correspondente.
- **Impacto real:** se a chave privada dev vazar (ou for usada por engano em ambiente de produção), atacante emite licença válida para qualquer tenant. Bypass do entitlement model.
- **Correção obrigatória:**
  1. remover fallback embutido em build de produção (build-arg);
  2. em runtime, `AION_LICENSE_PUBLIC_KEY` é mandatório quando `AION_PROFILE=production`;
  3. validar fingerprint da chave contra um conjunto conhecido (logado e comparado no boot).
- **Status:** **Reprovado**.

---

### F-05 — `AION_LICENSE_SKIP_VALIDATION=true` desabilita TODA a validação

- **Severidade:** S2 (RAD inválido — falta evidência de decisão consciente em production deploys)
- **Área:** Licença
- **Arquivo:** [aion/license.py:235-245](aion/license.py)
- **O que está errado:** uma env booleana skipa toda a checagem; só logger warning. Esquecer essa env em prod = sistema sem licença e sem Trust Guard, com tenant fixo "dev".
- **Correção obrigatória:** rejeitar essa env quando `AION_PROFILE=production`. Mensagem critical, exit.
- **Status:** **Reprovado**.

---

### F-06 — `event.data["input"]` com mensagem do usuário (PII vaza para `/v1/events`, `/v1/explain`, ARGOS)

- **Severidade:** S1
- **Área:** Privacidade / Promessa LGPD
- **Arquivo:** [aion/shared/telemetry.py:124-142, 190-197](aion/shared/telemetry.py)
- **O que está errado:** o construtor de `TelemetryEvent` atribui `input_text` cru ao campo `input` no `event.data`. `_sanitize_metadata` **não toca** em `input` (só no sub-dict `metadata`). `emit()` envia `event.data` para ARGOS quando `argos_telemetry_url` está configurado.
- **Promessa contradita:** [README.md:225-228](README.md):
  > "O que NUNCA sai: prompts, respostas, PII, dados de usuario."
- **Impacto real:** se ARGOS opt-in for ativado por um operator (ex: depois de DPA assinado), prompts contendo PII saem do ambiente do cliente. Mesmo sem ARGOS, `/v1/events` e `/v1/explain` retornam `input` cru via API admin.
- **Correção obrigatória:** sanitizar/hashear/redactar `input` antes do `emit()`. Política: gravar `input_hash`, `input_length`, `intent_label`, mas nunca o texto literal.
- **Status:** **Reprovado**.

---

### F-07 — `cost_saved_total` in-memory (volátil): "MENTIRA EXECUTIVA"

- **Severidade:** S1
- **Área:** Analytics / Métricas executivas
- **Arquivo:** [aion/shared/telemetry.py:38](aion/shared/telemetry.py); [aion/routers/observability.py:283-291](aion/routers/observability.py); [aion/routers/intelligence.py:108](aion/routers/intelligence.py)
- **O que está errado:** counters são variáveis module-level, zeram a cada restart. Dashboard executivo (`/v1/economics`, `/v1/intelligence/{tenant}/overview`) reporta "savings_usd" derivado desses counters. Cliente perde a história de economia em todo deploy.
- **Impacto real:** reunião executiva: "exibido US$ 5.000 economizados na sexta, US$ 0 economizados na segunda". Reputação queimada.
- **Correção obrigatória:** persistir em Redis com TTL longa OU emitir para time-series DB. NEMOS já persiste por trilha — usar essa fonte para `/v1/economics`.
- **Status:** **Reprovado**.

---

### F-08 — `total_spend_usd` exibe `cost_saved` como fallback (rotulagem invertida)

- **Severidade:** S2
- **Área:** Analytics
- **Arquivo:** [aion/routers/intelligence.py:108](aion/routers/intelligence.py)
- **O que está errado:** `"total_spend_usd": round(total_spend, 4) if total_spend else round(cost_saved, 4)`. Quando NEMOS sem dados, exibe economia rotulada como gasto.
- **Impacto real:** leitura executiva ambígua, decisão errada possível.
- **Correção obrigatória:** se `total_spend == 0`, retornar `null` ou `0.0`; nunca substituir por valor de outra métrica.
- **Status:** **Reprovado**.

---

### F-09 — Preços hardcoded em `models.yaml` sem fonte/timestamp

- **Severidade:** S2
- **Área:** Analytics / Custo
- **Arquivo:** [config/models.yaml](config/models.yaml)
- **O que está errado:** `cost_per_1k_input` / `cost_per_1k_output` por modelo, sem `pricing_source`, `pricing_observed_at`, `pricing_currency`. Quando OpenAI/Anthropic mudam preço, AION calcula errado.
- **Correção obrigatória:** schema YAML estendido com campos de origem; CI valida divergência (semanal); doc de release alerta para refresh.
- **Status:** **Reprovado**.

---

### F-10 — `/v1/explain/{request_id}` só funciona enquanto está no buffer in-memory

- **Severidade:** S1
- **Área:** Explainability / Compliance
- **Arquivo:** [aion/routers/observability.py:424-447](aion/routers/observability.py)
- **O que está errado:** lê do buffer (limit=1000); se request saiu, retorna `found:false`.
- **Impacto:** auditor pede explain de um request 30 dias atrás → produto responde "Request not found".
- **Correção obrigatória:** persistir explain payload em store durável (NEMOS Redis stream com TTL ≥ retention legal; ou Supabase para metadata; ou objeto WORM em S3).
- **Status:** **Reprovado**.

---

### F-11 — `AION_REQUIRE_TENANT=false` por default → bucket "default" colide múltiplos clientes

- **Severidade:** S1 (em deploy multi-tenant)
- **Área:** Multi-tenant boundary
- **Arquivo:** [aion/config.py:77](aion/config.py); [aion/middleware.py:674-682](aion/middleware.py)
- **O que está errado:** em produção multi-tenant, basta um cliente esquecer de enviar header → vai para bucket "default" misturando dados.
- **Correção:** default `true` para `AION_REQUIRE_TENANT` em build de produção; ou exigir setar quando `AION_PROFILE=production`.
- **Status:** **Reprovado** (em modo multi-tenant). Para single-tenant on-prem (memória do projeto), pode ser RAD aceito com `tenant=cliente_unico`.

---

### F-12 — `AION_REQUIRE_CHAT_AUTH=true` mas sem `AION_ADMIN_KEY` → chat anônimo silencioso

- **Severidade:** S1
- **Área:** Auth
- **Arquivo:** [aion/middleware.py:799-809](aion/middleware.py); [aion/main.py:119-145](aion/main.py)
- **O que está errado:** o middleware só valida quando `admin_key_str` está vazio... e quando `AION_ADMIN_KEY=""` o middleware passa o request **sem auth**. Boot avisa via `_env_problems` mas não bloqueia (só aborta se FAIL_MODE=closed).
- **Correção:** se `require_chat_auth=true` E `admin_key=""`, abortar startup OU rejeitar todos os chat requests com 503 "auth not configured".
- **Status:** **Reprovado**.

---

### F-13 — `X-Aion-Actor-Role` header aceito sem validação SSO upstream

- **Severidade:** S1
- **Área:** RBAC
- **Arquivo:** [aion/middleware.py:727-740](aion/middleware.py)
- **O que está errado:** chaves com role `console_proxy` (ou `sso_proxy`) viram "trusted source"; o role do ator é tomado do header `X-Aion-Actor-Role` sem prova criptográfica.
- **Impacto:** se a chave `console_proxy` vazar (logs, repo, CI), atacante envia `X-Aion-Actor-Role: admin` e ganha admin; nem o console SSO foi consultado.
- **Correção:** trocar header textual por JWT assinado pelo console (com claim `role`); AION valida assinatura.
- **Status:** **Reprovado**.

---

### F-14 — `/health` (público) revela license_id, expiry, restricted_features

- **Severidade:** S2
- **Área:** Reconhecimento
- **Arquivo:** [aion/routers/observability.py:39-48, 103-146](aion/routers/observability.py)
- **Correção:** mover `license_id`, `entitlement_valid_until`, `restricted_features` para `/version` (já protegido). `/health` minimal: status, mode, ready, degraded_components.
- **Status:** Reprovado (S2).

---

### F-15 — Streaming buffer-accumulate-flush sem cap de output tokens / payload

- **Severidade:** S2
- **Área:** Performance / Custo / Resiliência
- **Arquivo:** [aion/routers/proxy.py:491-565](aion/routers/proxy.py)
- **O que está errado:** `buffered_chunks: list[str] = []` cresce sem teto; só `_STREAM_TIMEOUT=300s` mitiga.
- **Correção:** hard cap `max_output_tokens` injetado no request; abortar se `len(buffered_chunks) > N`; alertar.
- **Status:** Reprovado (S2).

---

### F-16 — Sem per-request cost cap

- **Severidade:** S1
- **Área:** Cost engineering
- **Arquivo:** [aion/shared/budget.py:184-226](aion/shared/budget.py)
- **O que está errado:** budget é diário/mensal; uma request enorme pode consumir o mês inteiro.
- **Correção:** adicionar `per_request_max_cost_usd` em `BudgetConfig`; estimar cost antes de chamar; rejeitar 402 se excede.
- **Status:** Reprovado (S1).

---

### F-17 — Documentação infla contagem de testes ("702+" vs 201 reais)

- **Severidade:** S2
- **Área:** Documentação
- **Arquivo:** [docs/PRODUCTION_CHECKLIST.md:109,130](docs/PRODUCTION_CHECKLIST.md)
- **Como reproduzir:**
  ```bash
  grep -rch "^\(async \)\?def test_" tests/ | awk '{s+=$1} END {print s}'  # 201
  ```
- **Correção:** corrigir doc; se contar parametrize, mostrar fórmula; idealmente, CI publica número real (`pytest --collect-only -q | wc -l`) num badge.
- **Status:** Reprovado.

---

### F-18 — `aion/rbac.py` referenciado mas não existe

- **Severidade:** S3
- **Arquivo:** [docs/SECURITY_REPORT.md:36](docs/SECURITY_REPORT.md)
- **Correção:** atualizar caminho para `aion/middleware.py` e `aion/shared/contracts.py`.
- **Status:** Reprovado (S3).

---

### F-19 — `start.py` referenciado mas não existe; `AION_ADMIN_KEY` formato sem `:role` no doc

- **Severidade:** S3 / S2
- **Arquivo:** [docs/SECURITY_REPORT.md](docs/SECURITY_REPORT.md)
- **Correção:** revisão geral do `SECURITY_REPORT.md`.
- **Status:** Reprovado.

---

### F-20 — Legacy admin keys sem `:role` viram ADMIN silenciosamente

- **Severidade:** S2
- **Arquivo:** [aion/middleware.py:152-156](aion/middleware.py)
- **Correção:** rejeitar formato legacy; exigir `:role` explícito.
- **Status:** Reprovado.

---

### F-21 — Behavior dial promete "controle paramétrico" mas atua via prompt injection

- **Severidade:** S2
- **Arquivo:** [aion/metis/behavior.py:113-150](aion/metis/behavior.py)
- **O que está errado:** README exemplifica `objectivity / density / explanation / cost_target` como "controle paramétrico", mas internamente vira instruções injetadas no system prompt + cost_target → NOMOS. Não controla `temperature`, `top_p`, `top_k` direto.
- **Correção:** ou implementar mapeamento real para parâmetros do LLM, ou reposicionar promessa como "Behavior Profile" (instruções) em vez de "dial paramétrico".
- **Status:** Reprovado (S2).

---

### F-22 — Decision contract não inclui `modified_request`

- **Severidade:** S2
- **Arquivo:** [aion/contract/decision.py:201-226](aion/contract/decision.py)
- **O que está errado:** a versão pós-METIS do request não vai no contract; replay completo da decisão é impossível sem dump do `context.metadata`.
- **Correção:** incluir `original_request_hash`, `modified_request_hash`, `compression_ratio`, `policy_version_applied` no contract.
- **Status:** Reprovado.

---

### F-23 — `/v1/admin/rotate-keys` rotaciona em memória do processo, sem persistência nem coordenação

- **Severidade:** S2
- **Arquivo:** [aion/routers/data_mgmt.py:63-88](aion/routers/data_mgmt.py)
- **O que está errado:** `os.environ["AION_SESSION_AUDIT_SECRET"] = new_secret` é process-local; multi-replica fica desincronizado; nova HMAC quebra continuidade do chain antigo sem registrar `chain_break`.
- **Correção:** persistir em Vault/Secret Manager; rotação coordenada com rolling restart; janela dual-secret aceita; emitir entry `audit_secret_rotated` no chain.
- **Status:** Reprovado.

---

### F-24 — Dependências em `pyproject.toml` com `>=`, sem lockfile commitado

- **Severidade:** S3
- **Arquivo:** [pyproject.toml:11-26](pyproject.toml)
- **Correção:** uv/pip-tools/poetry para gerar lock; commitar; CI verifica drift.
- **Status:** Reprovado (S3).

---

### F-25 — Cache LRU por réplica, não distribuído

- **Severidade:** S2
- **Arquivo:** [aion/cache/__init__.py](aion/cache/__init__.py)
- **Correção:** distribuir via Redis (vector or k-v) ou aplicar session affinity no LB.
- **Status:** Reprovado.

---

### F-26 — Observabilidade sem labels de tenant em métricas Prometheus

- **Severidade:** S2
- **Arquivo:** [aion/routers/observability.py:174-232](aion/routers/observability.py)
- **Correção:** adicionar `tenant=...` label (cardinality controlada); ou expor agregado por tenant via `/v1/intelligence/{tenant}/...` e calcular fleet-wide separadamente.
- **Status:** Reprovado.

---

### F-27 — Eval suite adversarial (AI/LLM) sem regression baseline

- **Severidade:** S2
- **Área:** AI/LLM
- **Correção:** criar `tests/adversarial/` com 50+ casos públicos + baseline FP/TP; CI quebra se regredir.
- **Status:** Reprovado.

---

### F-28 — `seed_sandbox.py` sem gate de produção

- **Severidade:** S2
- **Arquivo:** [scripts/seed_sandbox.py](scripts/seed_sandbox.py)
- **Correção:** exigir `AION_ALLOW_SEED=true` env; refusal se `AION_PROFILE=production`.
- **Status:** Reprovado.

---

### F-29 — `_TENANT_PATTERN` regex não confirmado neste audit

- **Severidade:** S2 (até confirmar)
- **Arquivo:** [aion/middleware.py:683-687](aion/middleware.py)
- **Correção:** revisar regex (deve ser `^[a-z0-9_-]{1,64}$` ou similar restrito); cobrir test cases com `../`, `\x00`, NULL bytes, unicode tricks.
- **Status:** Não validado.

---

### F-30 — `_TRUSTED_PROXY_ROLES` lista hardcoded; sem registry/governance

- **Severidade:** S3
- **Arquivo:** [aion/middleware.py:730](aion/middleware.py)
- **Correção:** documentar política; centralizar em `aion/security/trusted_roles.py`.
- **Status:** Reprovado.

---

### F-31 — Header `X-Aion-Actor-Reason` sem sanitização → log poison

- **Severidade:** S2
- **Arquivo:** [aion/middleware.py:756-770, 430-431](aion/middleware.py)
- **Correção:** limit de tamanho, escape de control chars, strip HTML.
- **Status:** Reprovado.

---

### F-32 — `comparação` `provided_key not in key_roles` (dict lookup)

- **Severidade:** S3 (timing attack micro)
- **Arquivo:** [aion/middleware.py:718, 805](aion/middleware.py)
- **Correção:** `hmac.compare_digest` per chave conhecida.
- **Status:** Reprovado (S3).

---

### F-33 — Telemetria event sem `environment`, `feature_version`, `policy_version`, `model_prompt_hash`

- **Severidade:** S2
- **Área:** Analytics / AI/LLM versioning
- **Correção:** estender schema; CI valida presença.
- **Status:** Reprovado.

---

### F-34 — Console SSO trust dependente de configuração externa não validada neste audit

- **Severidade:** Não validado / S1 se mal configurado
- **Status:** Não validado.

---

### F-35 — Latency samples deque maxlen=1000 → p99 de janela curta em alto volume

- **Severidade:** S3
- **Arquivo:** [aion/shared/telemetry.py:39](aion/shared/telemetry.py)
- **Correção:** Prometheus histogram nativo (já recomendado em todas as guidelines).
- **Status:** Reprovado (S3).

---

### F-36 — Budget cap não é mandatório por design (em on-prem com chave LLM do cliente)

- **Severidade:** S1 (gravata na promessa de "controle de custo")
- **Área:** Cost engineering / Promessa de produto
- **Arquivos:** [aion/shared/budget.py](aion/shared/budget.py); [aion/routers/budget.py](aion/routers/budget.py)
- **O que está errado:** budget cap é configurado **sob demanda** via `PUT /v1/budget/{tenant_id}`. Não há setting equivalente a `AION_BUDGET_ENABLED=true` que torne cap mandatório no boot. Em deploy on-prem, se o operador esquecer de configurar o budget de cada workspace, AION proxia tudo sem teto — fatura do **cliente** com OpenAI/Anthropic explode.
- **Por que isso piora em on-prem:** em SaaS, "fatura sem cap" é problema do vendor (Baluarte). Em on-prem, é problema do **cliente**. A promessa de produto "controle de custo" só se sustenta se o cap está ativo; o produto delega essa garantia ao operador do cliente, sem default seguro.
- **Correção obrigatória:**
  1. setting `AION_BUDGET_DEFAULT_DAILY_USD=0.01` (valor mínimo seguro) ou `AION_REQUIRE_BUDGET_CONFIG=true` que abort no boot se nenhum tenant configurado tem budget.
  2. `/health` mostrar `"budget_configured": false` quando não há config — alerta visível.
  3. Documentação `pilot-onboarding.md` deixar evidente que cliente DEVE configurar budget no dia 0.
- **Status:** Reprovado.

---

## Sumário por severidade (CALIBRAÇÃO REVISADA — pós errata)

> Após declaração do dono do produto que AION é single-tenant on-prem (ver [errata-and-recalibration.md](errata-and-recalibration.md)).

- **S0:** 0
- **S1 (revisado):** F-03, F-04, F-06, F-07, F-10, F-12, F-16, F-36 → **~8 itens**
- **S2 (revisado, inclui ex-S1 rebaixados):** F-01, F-02, F-05, F-08, F-09, F-13, F-14, F-15, F-17, F-19 (parcial), F-20, F-21, F-22, F-23, F-25, F-26, F-27, F-28, F-29, F-31, F-33 → **~22 itens**
- **S3 (revisado, inclui F-11 rebaixado):** F-11, F-18, F-24, F-30, F-32, F-35 → **6 itens**
- **Não validado:** F-34

### Sumário por severidade (calibração ORIGINAL — antes da errata)

- **S1:** F-01, F-02, F-03, F-04, F-06, F-07, F-10, F-11, F-12, F-13, F-16 → 11 itens
- **S2:** 18 itens
- **S3:** 5 itens

A diferença: a errata rebaixa 4 achados (F-01, F-02, F-11, F-13) que assumiam multi-tenant cross-customer e adiciona F-36 que ganha peso em on-prem.
