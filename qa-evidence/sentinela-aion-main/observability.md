# Fase 8 — Observabilidade e Prova

| Evento crítico | Existe log? | Existe rastreio? | Existe evidência? | Gap |
|---|:---:|:---:|:---:|---|
| Request entrou (chat) | ✅ JSON log; `request_id` no header response ([main.py:97-99](aion/main.py)) | ✅ correlation_id propagado | ✅ telemetria + audit | — |
| Decisão BYPASS/BLOCK/PASSTHROUGH | ✅ event.data.decision | ✅ `request_id` | parcial: `/v1/explain` falha após buffer turnover | **explain durability** (F-18, S1) |
| Cache hit/miss | ✅ counter + `event.metadata.decision_source` ([telemetry.py:83](aion/shared/telemetry.py)) | ✅ `decision_source: "cache"|"pipeline"` | ok | — |
| Erro upstream LLM | ✅ counter `errors_total` + circuit breaker logs | ✅ `request_id` no error response | parcial — sem trace_id distribuído por default | OTel opt-in (P-13) |
| Block reason / risk category | ✅ `event.metadata.detected_risk_category`/`block_reason` | parcial — só dentro do buffer in-memory | falha quando buffer rotaciona | persistir histórico real |
| Audit chain entries | ✅ middleware audit + Redis chain tip + per-tenant deque | ✅ HMAC quando secret presente | gap: secret opcional → SHA-256 simples → chain forjável (SEC-3) | obrigar secret em production |
| License state | ✅ logger.info + `_log_license_state()` ([license.py:296-311](aion/license.py)) + `/health.trust_guard` | ✅ | ok | — |
| Auth pass-through warning | ✅ `/health.auth_warnings` ([observability.py:103-131](aion/routers/observability.py)) | log warning em boot | ok visibilidade, mas continua passando — operator pode ignorar | "nag mode": loggar a cada N requests; ou bloquear em `production` profile |
| Tenant mismatch (path_tenant != header) | ✅ JSON 403 + `/v1/audit` entry | ✅ | ok | — |
| Budget exceeded (429) | ✅ counter + log | ✅ | ok | — |
| Trust Guard heartbeat | ✅ background task + state file | parcial | ok visibility via `/health.trust_guard.last_heartbeat` | — |
| ESTIXE classifier degraded (no embedding model) | ✅ `/health.estixe.classifier == "unavailable"` ([observability.py:88-96](aion/routers/observability.py)) + degraded_components | ✅ Prometheus gauge `aion_classifier_degraded` | ok | — |
| Velocity alert | ✅ counter + `event.metadata.velocity_alert` | parcial | ok visualização, mas sem alerting integrado | webhook/PagerDuty integration |
| Circuit breaker trip | ✅ Redis state + log | ✅ | ok cross-replica | — |
| PII detection / sanitization | ✅ counts em `event.metadata.pii_violations`, `pii_audited` | ✅ | gap: `event.data.input` ainda crú (SEC-6, F-10) | sanitizar `input` antes de `emit()` |
| ARGOS forwarding success/failure | parcial (logger.warning em fail) | sem retry | aceitável (opt-in best-effort) | — |
| Supabase write success/failure | ✅ logger.debug + circuit breaker | ✅ | ok | — |

## SLIs / SLOs

`/metrics` Prometheus expõe ([observability.py:174-232](aion/routers/observability.py)):

- `aion_requests_total` (counter)
- `aion_decisions_total{decision}` (counter por decisão)
- `aion_errors_total`
- `aion_tokens_saved_total` ⚠ in-memory volátil
- `aion_cost_saved_total` ⚠ in-memory volátil
- `aion_buffer_size`, `aion_requests_in_flight`
- `aion_pipeline_latency_ms{quantile=0.5|0.95|0.99}` ⚠ derivado de `_latency_samples` (deque maxlen=1000) — janela curta
- `aion_classifier_degraded{replica}`, `aion_estixe_risk_categories{replica}`, `aion_estixe_shadow_categories{replica}`
- `aion_classify_cache_*{replica}` e `aion_decision_cache_*{replica}` (size, hits, misses, hit_rate, evictions)
- `aion_tier_hits_total{replica,tier}`

**Gaps:**

- ❌ **Sem labels de tenant em métricas Prometheus** — todos os tenants colidem em counters globais; impossível ter "savings por tenant" via Prometheus. Resolver com label `tenant=...` (cardinality controlada).
- ❌ **Sem histograma de cost** (só counter); impossível ver distribuição de custo por request.
- ❌ **`aion_buffer_size`** sem label de fila; em multi-buffer (audit, events, latency_samples) confunde.
- ⚠ Latency samples maxlen=1000 — em alto RPS, p99 de "última hora" some em segundos. Usar histograma persistente (Prometheus histogram) ou agregação externa.

## Healthcheck

- `/health` retorna 200/207/503 — bom design.
- `/ready` boolean — bom para K8s.
- ⚠ `/health` expõe **detalhes sensíveis** (license_id, expiry) — SEC-7.

## Distributed tracing (OpenTelemetry)

- Setup opt-in em [aion/observability.py:25-66](aion/observability.py); chamado em [main.py:163-166](aion/main.py).
- Sem export por default; cliente precisa setar `OTEL_EXPORTER_OTLP_ENDPOINT`.
- Documentação inconsistente (L-10): claim "fora de escopo v1" mas código existe.
- Aceitável como opt-in; documentar como recomendado para produção.

## Audit trail visualização

- `/v1/audit` retorna últimas N entradas por tenant.
- Hash chain (`prev_hash`) + HMAC (quando secret) ✓.
- ⚠ Sem export imutável (S3/objeto WORM); sem assinatura externa (transparency log).
- ⚠ Sem prova de continuidade quando secret rotaciona (`rotate-keys`) — deveria registrar `chain_break` event.

## Veredito Observabilidade

- **Forte:** estrutura básica (logs JSON, /metrics Prometheus, audit chain, /health, OTel hookable).
- **Fraco:** durabilidade (in-memory deques), tenant cardinality em métricas, expor explainability persistente, alerting integrado (sem hooks built-in para PagerDuty/Slack).
- **Conclusão:** observabilidade **funciona em dev/POC**, mas **não atende SLA enterprise** (auditor pede explain de 90 dias atrás → produto responde "Request not found").

Severidade dominante de gaps: **S1/S2**.
