# Fase 4 — Segurança Sem Misericórdia

| # | Risco | Local | Como explorar | Impacto | Severidade | Correção obrigatória |
|---|---|---|---|---|:---:|---|
| SEC-1 | Operator com permissão `data:delete` apaga dados de QUALQUER tenant | [routers/data_mgmt.py:25-60](aion/routers/data_mgmt.py); RBAC em [middleware.py:705-754](aion/middleware.py) | login com `key:operator`, `X-Aion-Tenant: vitima`, `DELETE /v1/data/vitima` | LGPD violation cross-customer | **S1** | atrelar `operator_id` ao `tenant_id` permitido (claim JWT ou tabela ownership); rejeitar 403 se mismatch |
| SEC-2 | Operator pode ler insights de qualquer tenant via `/v1/intelligence/{tenant}/...` | [routers/intelligence.py:20-261](aion/routers/intelligence.py) | mesmo método que SEC-1 | leak de "savings", PII intercept counts, top_block_reason, model usage | **S1** | mesmo fix |
| SEC-3 | `AION_SESSION_AUDIT_SECRET` opcional → audit chain forjável | [middleware.py:362-369](aion/middleware.py) | omitir env; entradas viram SHA-256 simples; recompor chain | trail tamper-evidence falsa | **S1** | exigir secret em runtime, abortar startup se ausente em modo "production" |
| SEC-4 | Chave pública Ed25519 embutida é DEV; sem enforcement de override em prod | [license.py:38-42](aion/license.py) | obter a chave dev (já está no repo público), assinar JWT com chave privada dev (que existe localmente em mãos da Baluarte ou em vazamento), AION aceita | bypass de licenciamento | **S1** | build production exige `AION_LICENSE_PUBLIC_KEY`; CI valida fingerprint conhecido; remover fallback embutido |
| SEC-5 | `AION_LICENSE_SKIP_VALIDATION=true` desabilita TUDO de licença | [license.py:235-245](aion/license.py) | env esquecida em deploy de prod | bypass total Trust Guard / entitlement / expiração | **S2** | rejeitar essa env quando `AION_PROFILE=production`; logging crítico, não warning |
| SEC-6 | `event.data["input"]` carrega mensagem do usuário sem sanitização | [telemetry.py:124-142, 190-197](aion/shared/telemetry.py) | enviar `chat/completions` com mensagem contendo PII; ler `/v1/events`; ARGOS receberá PII se ligado | **PII vaza para `/v1/events`, `/v1/explain`, ARGOS** | **S1** | hashear ou redactar `input` antes de `emit()`; sanitizer dedicado (segue `_SAFE_METADATA_KEYS` model) |
| SEC-7 | `/health` (público) revela `license_id`, `entitlement_valid_until`, `restricted_features`, `auth_warnings`, `aion_mode` | [routers/observability.py:75-162](aion/routers/observability.py) | `curl /health` | reconhecimento de janela de expiração, tier do cliente, modo de operação | **S2** | mover detalhes de licença para `/version` (já protegido); manter `/health` minimal |
| SEC-8 | Default `AION_REQUIRE_TENANT=false` + `AION_REQUIRE_CHAT_AUTH=true` sem `AION_ADMIN_KEY` setada → chat anônimo + bucket "default" colide | [config.py:76-77](aion/config.py); [middleware.py:799-809](aion/middleware.py); [main.py:119-145](aion/main.py) | startar sem env críticas; `/health.auth_mode == "pass_through"` mas chat aceita | dados de tenants distintos colidem; auditoria fica sem caller identity | **S1** | sair (sys.exit) se `AION_PROFILE=production` e qualquer dessas faltando |
| SEC-9 | `X-Aion-Actor-Role` aceito como verdade absoluta para chaves `console_proxy` | [middleware.py:727-740](aion/middleware.py) | obter chave console_proxy (provavelmente longa, mas se vazar) → enviar `X-Aion-Actor-Role: admin` em qualquer request | RBAC bypass mediado por chave `console_proxy` | **S1** | mover role para JWT assinado pelo console (chave par. assinatura), validar no AION |
| SEC-10 | Header `X-Aion-Actor-Reason` injetado no audit `details` sem sanitização | [middleware.py:756-770, 430-431](aion/middleware.py) | enviar reason gigante / payload XSS / PII | log poison; PII em audit | **S2** | limit de tamanho + escape; eliminar HTML/control chars |
| SEC-11 | Legacy admin keys sem `:role` viram admin silenciosamente | [middleware.py:152-156](aion/middleware.py) | configurar `AION_ADMIN_KEY=key1,key2` (sem role) → todas viram ADMIN | escalonamento implícito | **S2** | rejeitar formato legacy; exigir `:role` explícito |
| SEC-12 | Streaming buffer-accumulate-flush sem cap em tokens de output | [routers/proxy.py:491-565](aion/routers/proxy.py) | upstream gera 1M+ tokens (ataque ou bug) | OOM no pod; queda; possível DoS local | **S2** | hard cap `max_output_tokens` antes do upstream; trigger de abort se buffer > N MB |
| SEC-13 | `cli.py` `host="0.0.0.0"` | [docs/SECURITY_REPORT.md:14](docs/SECURITY_REPORT.md) | bind direto sem TLS termination na frente | exposição direta | **S3** RAD viável (assumindo ngnix/ALB sempre na frente) | documentar exigência explícita; healthcheck que falha sem `AION_BEHIND_PROXY=true` |
| SEC-14 | Comparação de `provided_key not in key_roles` (dict lookup) | [middleware.py:718, 805](aion/middleware.py) | timing-attack micro (Python dict lookup é tipicamente constante mas não garantido para chaves de tamanhos variados) | descoberta de chave por timing (improvável mas possível em ambientes ruidosos) | **S3** | `hmac.compare_digest` para cada chave conhecida (consistent-time) |
| SEC-15 | Dependências em `pyproject.toml` com `>=`; sem lockfile no repo | [pyproject.toml:11-26](pyproject.toml) | upgrade silencioso introduz CVE / breaking change | supply chain | **S3** | gerar e commitar `requirements-lock.txt` (uv/pip-tools/poetry); CI verifica drift |
| SEC-16 | Telemetria interna em buffer in-memory; perda de eventos em queda | [telemetry.py:21-23](aion/shared/telemetry.py) | matar pod | dados de auditoria/explainability voláteis | **S2** | persistência durável (Redis stream + sink S3/ClickHouse) |
| SEC-17 | `/v1/admin/rotate-keys` rotaciona em memória do processo, sem persist + sem invalidate del chain antigo | [routers/data_mgmt.py:63-88](aion/routers/data_mgmt.py) | rotação parcial entre réplicas; chain quebra | trilha desincronizada | **S2** | persistir secret em segredo gerenciado (Vault/Secret Manager); rotação coordenada com rolling restart e janela de aceitação dual-secret |
| SEC-18 | Path-traversal/injection em `tenant` (`_TENANT_PATTERN.match(tenant)` — regex não auditado neste run) | [middleware.py:683-687](aion/middleware.py) | tentar `../`, `\x00`, NULL bytes em header | possível key collision em Redis (`aion:audit:..`) | **S2** | confirmar regex (deveria ser `^[a-z0-9_-]{1,64}$` ou similar); audit dos tests |
| SEC-19 | `seed_sandbox.py` populando dashboards | [scripts/seed_sandbox.py](scripts/seed_sandbox.py) | invocar em ambiente errado | dashboards mostram dados sintéticos | **S2** | gate por env explícita (`AION_ALLOW_SEED=true`); refusal em production |
| SEC-20 | Documentação alega "Zero CVEs" como fato perpétuo | [SECURITY_REPORT.md:18-29](docs/SECURITY_REPORT.md) | depender da claim, não rerodar pip-audit | regressão silenciosa | **S3** | CI semanal (citado mas não vimos workflow); commitar lock e checar weekly |

---

## AI/LLM Risks (Sub-fase 4.1)

### Aplicabilidade
✅ **Aplicável**. AION é proxy LLM; usa embeddings para classificação (sentence-transformers all-MiniLM-L6-v2); pipeline de policy + risk classification + bypass + routing inteligente.

### Auditoria

| Tópico | Status | Evidência | Severidade |
|---|---|---|:---:|
| **Prompt injection direto e indireto** | parcial | ESTIXE faz semantic classification + policy regex; embedding-based — sujeita a adversarial perturbation; "continuity boost +0.04" facilita ataque multi-turno após estabelecer contexto benigno ([estixe/__init__.py:162](aion/estixe/__init__.py); estixe/classifier.py:117-199) | S2 |
| **System prompt leakage** | gap | não vi blindagem para perguntas tipo "repeat your instructions" — depende do LLM upstream | S2 (RAD: out of scope, gerenciado pelo policy do cliente) |
| **Output validation** | parcial | METIS post pode `optimize` resposta — escopo não claro (pode alterar fatos) ([metis/__init__.py:131-146](aion/metis/__init__.py)); ESTIXE output guard checa PII/risk; mas não há schema validation | S2 |
| **Hallucination boundaries** | gap | não há ground truth nem sistema de citation enforcement (esperado para um proxy genérico) | S3 |
| **Eval suite (adversarial)** | parcial | tests/test_threat_detector.py (26 tests), test_chaos.py, test_poc_security.py existem; mas não há eval set adversarial estruturado com regression tracking | S2 |
| **Model fallback** | ✅ ok | NOMOS fallback chain ([nomos/router.py:98-111](aion/nomos/router.py)); ok | — |
| **Token budget runaway / hard cap** | parcial | cap diário/mensal por tenant ✓; **sem per-request cap** → uma request enorme pode esgotar mês inteiro; streaming sem cap de output tokens (SEC-12) | **S1** |
| **PII e dados sensíveis em prompts** | parcial | ESTIXE detecta + masca; **mas `event.data["input"]` carrega texto cru** (SEC-6) → vaza para telemetria | **S1** |
| **Capability escape** | ✅ ok | `/v1/decide` retorna template canônico do YAML; não há "tool call" não-controlado | — |
| **Versionamento de prompt + modelo + temp + tools + parâmetros** | gap | sem `model_prompt_hash` no contract; YAML de intents/policies não tem checksum/versionamento explícito; troca de prompts/models não tem reeval gating | **S2** |
| **RAG-specific** | N/A | AION não é RAG (proxy puro com cache semântico, não busca em corpus de documentos do cliente) | — |

### Bloqueios automáticos AI/LLM

- ❌ **Prompt injection com capability escape** — não evidenciado; `/v1/decide` é seguro.
- ❌ **Output de LLM gravado direto em datastore sem validação** — não evidenciado; PII guard roda antes da gravação no buffer.
- ⚠ **System prompt sem versionamento + modelo trocável remotamente** — `models.yaml` não tem `version` por linha, mas tem `version: "1.0"` global; **modelos podem ser trocados (hot reload via /v1/modules/{name}) sem reeval automático** → S1 atenuado para S2 com RAD viável (ADR + monitoramento).
- ⚠ **Ausência de eval suite em produto que toma decisão automatizada** — existem testes mas não eval set adversarial com baseline numérica estabilizada → S2.

### Achados consolidados AI/LLM

| Severidade | Itens |
|:---:|---|
| **S1** | SEC-6 (PII em telemetry), token budget per-request gap |
| **S2** | adversarial robustness do classifier, METIS post optimization scope, prompt/model versioning |
| **S3** | hallucination boundaries (escopo do produto) |
