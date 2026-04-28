# AION — Production Readiness Checklist

Este documento lista o que deve ser verificado/ativado antes de colocar o AION
em produção multi-tenant. O **ambiente simulado** (`start.py`) é bom para demo
e dev; produção requer os itens abaixo.

## 1. Infraestrutura

- [ ] **Redis configurado e reachable** (`REDIS_URL=rediss://...`)
  - Sem Redis: velocity detection é process-local (facilita bypass via round-robin)
  - Sem Redis: overrides persistem em arquivo local — não compartilham entre réplicas
- [ ] **Multi-replica com session affinity opcional** (para coherência local do bypass cache)
- [ ] **Health check em load balancer apontando para `/ready`** (não `/health`)
- [ ] **Embedding model cacheado localmente** (não depender de HuggingFace em runtime):
  - Pre-baixar `sentence-transformers/all-MiniLM-L6-v2` no container
  - Setar `HF_HUB_OFFLINE=1` para prevenir calls externos

## 2. Licença e Segurança

- [ ] **`AION_LICENSE` configurado** — JWT fornecido pela Baluarte ou arquivo `aion.lic` na raiz
  - Licença validada offline (Ed25519) — sem dependência de rede
  - Estado visível em `/health` → `trust_guard.trust_state`
- [ ] **`AION_SESSION_AUDIT_SECRET` definido** — segredo HMAC-SHA256 para trilha de auditoria
  - Gerar: `openssl rand -hex 32`
  - Sem este segredo, a trilha de auditoria não tem assinatura (sem evidência de integridade)
- [ ] **`AION_REQUIRE_CHAT_AUTH=true`** — nenhum request anônimo em prod
- [ ] **`AION_REQUIRE_TENANT=true`** — header `X-Aion-Tenant` obrigatório
- [ ] **`AION_ADMIN_KEY` definido com roles** (rotacionável: `"key1:admin,key2:operator"`)
- [ ] **`AION_CORS_ORIGINS` restritivo** — só origens conhecidas, nunca `*`
- [ ] **API keys de provider em secrets manager**, nunca em `.env`
- [ ] **Rate limits calibrados por tenant** via `AION_CHAT_RATE_LIMIT` e overrides
- [ ] **TLS terminator à frente** (nginx/ALB) — AION serve HTTP interno

## 3. Observabilidade

- [ ] **Scrape de `/metrics`** (Prometheus) a cada 15-30s
- [ ] **Drain de `/v1/events`** para storage persistente (Redis→ClickHouse, S3, etc)
  - O buffer é in-memory, `maxlen` limitado — eventos antigos são descartados
- [ ] **Alerts configurados**:
  - Block rate > 10% sustentado (ataque distribuído ou configuração errada)
  - p95 > 500ms (degradação de performance)
  - `aion_errors_total` crescendo (upstream instável)
  - `estixe.degraded=true` em `/health` (classifier sem embedding model)
  - `velocity_alert=true` sustentado em algum tenant
- [ ] **Logs estruturados** já em JSON — ingerir via ELK/Loki/Datadog
- [ ] **Distributed tracing** (OpenTelemetry) — v2, hoje não está pronto

## 4. Configuração do ESTIXE

- [ ] **Revisar `risk_taxonomy.yaml`** para o domínio do cliente:
  - Adicionar seeds em PT-BR específicos do setor
  - Remover categorias irrelevantes (ex: `third_party_data_access` em SaaS que não tem multi-tenancy)
  - Ajustar `threshold` por categoria após observar produção
- [ ] **Shadow mode para categorias novas**:
  - Marcar `shadow: true` em categoria nova por 7-14 dias
  - Monitorar `metadata.shadow_risk_category` em `/v1/events`
  - Confirmar FP rate < 1% antes de promover (remover `shadow: true`)
- [ ] **Velocity calibrado**:
  - `ESTIXE_VELOCITY_BLOCK_THRESHOLD` (default 5): quantos blocks dispara tightening
  - `ESTIXE_VELOCITY_WINDOW_SECONDS` (default 60): janela de observação
  - `ESTIXE_VELOCITY_TIGHTEN_DELTA` (default 0.05): quanto apertar
- [ ] **PII policy por tenant**: `credit_card=block` para financeiro, `email=audit` para outros

## 5. LLM Provider

- [ ] **`AION_DEFAULT_BASE_URL` correto para o provider** (ou `None` para default OpenAI)
- [ ] **Circuit breaker testado** (`aion.proxy._check_circuit_breaker`):
  - Derrubar upstream temporariamente e verificar fallback
- [ ] **`AION_FAIL_MODE`**: 
  - `open` = se AION cai, LLM é chamado sem proteção (disponibilidade)
  - `closed` = se AION cai, 503 (segurança)
  - Escolha consciente para o risk profile do cliente

## 6. Streaming

- [ ] **Verificar UX com `stream:true`**: hoje AION acumula buffer e flusha ao final (safety > UX)
- [ ] **Timeout adequado** em `_STREAM_TIMEOUT` (default 60s)

## 7. Compliance / LGPD

- [ ] **Retention de eventos**: `AION_TELEMETRY_RETENTION_HOURS` (default 168 = 7 dias)
- [ ] **Endpoint `/v1/data/delete` testado** — LGPD direito ao esquecimento
- [ ] **Audit log imutável** (Redis com persistência ou write-only DB)
- [ ] **PII não logado**: verificar que `input_text` em eventos não contém PII não-redacted

## 8. Disaster Recovery

- [ ] **Backup do `.runtime/overrides.json`** (ou Redis snapshot) — config de tenant
- [ ] **Backup do `risk_taxonomy.yaml` + `intents.yaml`** versionados em git
- [ ] **Procedimento documentado**: o que fazer se Redis cai, se embedding model falha carregar, etc
- [ ] **Killswitch testado**: `AION_SAFE_MODE=true` bypassa tudo — testar com traffic ativo

## 9. Performance baselines

Após rodar `python stress_test.py --workers 50 -n 100` em ambiente prod-like:

| Métrica | Target mínimo |
|---|---|
| Taxa de sucesso | ≥ 99.5% |
| p50 latência | < 50ms |
| p95 latência | < 500ms |
| p99 latência | < 2000ms |
| RPS sustentado | ≥ 100 (por réplica) |
| Attack block rate | ≥ 95% |
| Benign false-positive rate | < 0.1% |

## 10. Pre-deploy

- [ ] Rodar `pytest tests/` em staging — **702+ testes, 0 falhas**
- [ ] Rodar stress test em staging — **todos critérios OK**
- [ ] Smoke test com traffic real sombreado (mirror produção por 24h)
- [ ] Runbook de rollback documentado

## Estado atual

| Item | Status | Nota |
|---|---|---|
| Licença Ed25519 (offline) | ✅ implementado | `aion/license.py` — sem phone-home |
| Trust Guard (integridade + entitlement) | ✅ implementado | `aion/trust_guard/` |
| Redis fallback | ✅ implementado | Velocity usa Redis quando disponível |
| Overrides persistentes | ✅ implementado | Arquivo JSON sem Redis; Redis quando disponível |
| Streaming output guard | ✅ implementado | Buffer-accumulate-flush (v1) |
| Shadow mode | ✅ 1 categoria em observação | `social_engineering` |
| Hot-reload guardrails | ✅ implementado | `POST /v1/estixe/guardrails/reload` |
| Telemetria ESTIXE completa | ✅ implementado | shadow/velocity/flagged em `/v1/events` |
| Supabase writer (metadados) | ✅ implementado | `aion/supabase_writer.py` — opt-in via env var |
| Trilha de auditoria hash-chained | ✅ implementado | `aion/middleware.py` — HMAC-SHA256 |
| Budget cap por tenant | ✅ implementado | `PUT /v1/budget/{tenant}` |
| Sessão de auditoria LGPD | ✅ implementado | `GET /v1/session/{id}/audit` |
| Test suite | ✅ 702 testes | `pytest tests/` |
| Distributed tracing (OTel) | ❌ fora de escopo v1 | |
| Offline embedding | ✅ bundled no Docker | `HF_HUB_OFFLINE=1`, modelo em `/opt/hf-model` |
