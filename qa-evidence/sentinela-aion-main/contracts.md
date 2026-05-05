# Fase 2 — Contratos ou Caos

| Contrato | Cliente espera | Produtor entrega | Divergência | Impacto | Severidade |
|---|---|---|---|---|:---:|
| `/v1/economics` | "tokens_saved", "cost_saved_usd" como métricas históricas duráveis | counters in-memory que zeram em todo restart ([telemetry.py:38](aion/shared/telemetry.py)) | promessa vs realidade | dashboard executivo volátil | S1 |
| `/v1/intelligence/{tenant}/overview.economics.total_spend_usd` | "gasto total" | exibe `cost_saved` (oposto de gasto) quando `total_spend == 0` ([intelligence.py:108](aion/routers/intelligence.py)) | rotulagem invertida | leitura executiva ambígua | S2 |
| `/v1/explain/{request_id}` | reconstrução de qualquer request auditável | só requests no buffer ~1.000 in-memory ([observability.py:430-447](aion/routers/observability.py)) | retenção real << prometida | "Request not found" inevitável após o turnover do buffer | S1 |
| `/v1/audit` | trilha tamper-evident HMAC-SHA256 | SHA-256 simples (sem HMAC) quando `AION_SESSION_AUDIT_SECRET` ausente ([middleware.py:362-369](aion/middleware.py)) | "tamper evidence theater" — texto literal do `_env_problems` no boot | trilha forjável; auditoria externa contestável | S1 |
| `/v1/data/{tenant}` (LGPD delete) | só o "dono" do tenant pode deletar | `path_tenant == header tenant` é checado, **mas RBAC não amarra operator → tenant** ([data_mgmt.py:25-60](aion/routers/data_mgmt.py)) | qualquer operador com `data:delete` pode apagar qualquer tenant | LGPD deletion acidental ou maliciosa entre clientes | S1 |
| `/v1/intelligence/{tenant}/overview` | dados isolados por tenant | path_tenant check existe, mas a falta de ownership permite admin ler insights de outros tenants ([intelligence.py:20-122](aion/routers/intelligence.py)) | mesmo gap acima | leak de "savings", "block reasons", "PII intercepts" entre tenants | S1 |
| `/v1/events` | "metadata only — nunca conteúdo de mensagens" (claim do README) | `event.data["input"] = input_text` ([telemetry.py:139](aion/shared/telemetry.py)) | mensagem do usuário gravada bruta; sanitização só em `metadata` | PII vaza para `/v1/events`, `/v1/explain`, ARGOS | S1 |
| `/v1/intelligence/{tenant}/compliance-summary` | `audit_trail_signed` true se compliance ok | `bool(os.environ.get("AION_SESSION_AUDIT_SECRET"))` ([intelligence.py:176](aion/routers/intelligence.py)) | reflete env var, não a integridade real do chain | flag de compliance pode estar `true` mesmo se chain truncado/forjado | S2 |
| Header `X-Aion-Actor-Reason` | trail de auditoria útil | concatenado em `details` sem sanitização ([middleware.py:430-431, 758-770](aion/middleware.py)) | operador pode injetar PII/HTML/string longa | log poison + PII em audit | S2 |
| `models.yaml.cost_per_1k_input/output` | preços atualizados | hardcoded; sem source/timestamp/refresh | drift vs billing real | "savings" e "estimated_without_aion" calculados com preço errado | S2 |
| `DecisionContract` | reproduzir decisão | não inclui `modified_request` (após METIS) ([contract/decision.py:201-226](aion/contract/decision.py)) | replay falha após compressão/rewriting | reprodução incompleta para auditoria/debug | S2 |
| `_TRUSTED_PROXY_ROLES` (`X-Aion-Actor-Role`) | console SSO repassa role do usuário | aceita header sem validar SSO upstream ([middleware.py:730-740](aion/middleware.py)) | operador com chave `console_proxy` pode forjar role do ator | RBAC bypass se chave `console_proxy` vazar | S1 |
| `cli.py` `host="0.0.0.0"` | bind seguro | bind em todas as interfaces, marcado como falso-positivo ([SECURITY_REPORT.md:14](docs/SECURITY_REPORT.md)) | em ambientes sem nginx/firewall na frente, AION fica exposto | erro de operação | S3 (RAD viável se TLS terminator está na frente) |
| `models.yaml.api_key_env` | env distinta por modelo (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) | aceito | ok | — | S0 |
| `EstixeResult.bypass_response_text` | resposta gerada | template do YAML ([estixe/data/intents.yaml]) | é por design (zero-token), mas precisa transparência ao cliente | UX engano se não documentado | S3 |
| Chat endpoints `/v1/chat/completions`, `/v1/decide` | autenticadas quando `AION_REQUIRE_CHAT_AUTH=true` | se `AION_ADMIN_KEY=""`, auth é silenciosamente desabilitada ([middleware.py:799-809](aion/middleware.py), warning emitido em `/health.auth_warnings`) | promessa funcional não é ativa por default | tráfego de chat anônimo passa | S1 |
| `aion-console` envia `X-Aion-Actor-Role` | role correta do usuário SSO | depende do mapping no console (não auditado) | sem teste e2e SSO→Console→AION | possível mismatch que vira RBAC bypass | S2 |
| `/health` | status público, sem segredos | expõe `license_id`, `entitlement_valid_until`, `restricted_features`, `auth_warnings`, `aion_mode` ([observability.py:39-48, 103-146](aion/routers/observability.py)) | reconhecimento gratuito de configuração e expiração | atacante planeja janela de outage; concorrente lê tier do cliente | S2 |

## Eventos esperados vs disparados

`TelemetryEvent` ([telemetry.py:109-142](aion/shared/telemetry.py)):

| Campo | Tipo | Comentário |
|---|---|---|
| `schema_version` | str ("1.0") | ✓ |
| `event_type` | str | sem enum/registry oficial — eventos novos podem entrar sem revisão |
| `module` | str | livre |
| `request_id` | str | ✓ correlation |
| `decision` | str | livre (deveria ser enum: bypass\|block\|passthrough\|fallback) |
| `model_used` | str | ✓ |
| `tokens_saved`, `cost_saved`, `latency_ms` | num | ✓ |
| `tenant` | str | ✓ |
| `input` | str | ⚠ texto cru do usuário |
| `timestamp` | float (epoch) | ⚠ sem timezone explícito; ISO 8601 ausente |
| `metadata` | dict (whitelisted) | ✓ |

**Sem `correlation_id` global** (multi-serviço): só `request_id` interno. Cross-service tracing depende do OTel (opt-in).

**Sem `environment`** (`prod`/`stg`/`dev`) — só pode ser inferido por replica_id ou por cliente externo.

**Sem `feature_version`** ou `model_prompt_hash` — não é possível rastrear qual versão de prompt/modelo gerou o evento.

## Recomendações curtas

1. Pinar fonte e timestamp de preços em `models.yaml`; auditar refresh.
2. Persistir `cost_saved_total` em Redis ou time-series DB; ou apresentar a métrica como "since last restart" explicitamente.
3. Sanitizar `event.data["input"]` antes de gravar/forwardar (whitelist de tokens, hash, ou substituir por hash + length + intent).
4. Escrever `/v1/explain` lendo de NEMOS/Redis (não do buffer volátil).
5. Adicionar tabela `tenant_owners(operator_key, tenant)` ou claim no JWT do ator e checar antes de qualquer escrita destrutiva por tenant.
6. Tornar `AION_SESSION_AUDIT_SECRET` **obrigatório** quando `AION_FAIL_MODE=closed` (já é) **e** quando `pre-launch` mode (não há). Idealmente, `AION_PROFILE=production` exige tudo (segredo, key, tenant header).
7. Validar `X-Aion-Actor-Role` contra um JWT assinado pelo console em vez de aceitar header textual.
