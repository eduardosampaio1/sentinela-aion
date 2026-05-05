# Fase 7 — Performance, Escala, Resiliência + Cost Engineering

| # | Ponto | Risco | Evidência | Impacto em escala | Correção |
|---|---|---|---|---|:---:|
| P-1 | Streaming buffer-accumulate-flush sem cap de output tokens | OOM | [routers/proxy.py:491-565](aion/routers/proxy.py); `_STREAM_TIMEOUT=300s` | upstream gera 1M+ tokens (bug ou ataque) → buffer cresce em RAM → kill | hard cap `max_output_tokens` no request; abort se `len(buffered_chunks) > LIMIT` | S2 |
| P-2 | Rate limit fallback in-memory por processo | bypass via round-robin | [middleware.py:297-348](aion/middleware.py) | sem Redis, cada réplica enforça independente; cliente excede limite real | exigir Redis em production via env check; se Redis off, log critical | S2 |
| P-3 | Cache LRU per-replica (não distribuído) | hit rate degrada | [cache/__init__.py](aion/cache/__init__.py) | multi-replica sem session affinity → cache miss; "tokens_saved" volátil | distribuir cache (Redis vector or pgvector) ou implementar session affinity | S2 |
| P-4 | `_event_buffer` deque maxlen=10.000 | perda de eventos | [telemetry.py:23](aion/shared/telemetry.py) | em alto volume (centenas de RPS), 10k eventos cobrem ~minutos | drain assíncrono para Redis stream / S3 / ClickHouse | S1 |
| P-5 | Counters in-memory (`_counters`, `_cost_saved_total`) | métricas voláteis | [telemetry.py:29-39](aion/shared/telemetry.py) | restart zera; multi-replica não agrega | persistir em Redis com TTL longa ou time-series DB | S1 |
| P-6 | Circuit breaker threshold=5 / recovery=30s | bom default mas hardcoded | [proxy.py:41-164](aion/proxy.py) | cargas burst podem oscilar; sem dynamic tuning | tunable via env (já existe) ✓; falta auto-adjust | S3 |
| P-7 | Retry exp backoff base=1s, max=10s, max_retries=3 | bounded ✓ | [proxy.py:273-345](aion/proxy.py) | ok | — | — |
| P-8 | Aprovação sweep loop a cada 60s | lazy resolution | [main.py:50-85](aion/main.py) | aprovações expiram com até 60s de delay | aceitável; ou usar timer scheduler preciso (priorityqueue) | S4 |
| P-9 | NEMOS snapshot baselines hourly | demora em primeiro relatório | [main.py:39-47](aion/main.py) | dashboards de tendência precisam de 24h+ para signal | aceitável | — |
| P-10 | Embedding model cold-start ~Xs | latência primeiro request | [main.py:170-179](aion/main.py) | log "Cold start: ESTIXE initialized in X.Xs" | já preload no lifespan ✓ | — |
| P-11 | Supabase fire-and-forget circuit breaker 30s | dado de telemetria pode ser perdido | [supabase_writer.py:59-75](aion/supabase_writer.py) | aceitável (best-effort) | — | — |
| P-12 | `forward_request` httpx pool | bom default | [proxy.py:83-96](aion/proxy.py) | timeouts conservadores | ok | — |
| P-13 | Multiplos backgrounds tasks sem cancellation graceful no shutdown | possível leak | [main.py:203-208](aion/main.py) | task.cancel() mas sem await | aguardar conclusão das tasks no shutdown | S3 |

---

## Cost Engineering (Sub-fase 7.1)

| # | Vetor | Existe guard? | Custo atual / Risco | Correção |
|---|---|:---:|---|:---:|
| C-1 | **Hard cap diário/mensal por tenant** (LLM tokens) | ✅ | enforced antes do call ([budget.py:184-226](aion/shared/budget.py)) | — |
| C-2 | **Hard cap por request** | ❌ | uma request enorme pode esgotar mês | adicionar `per_request_max_cost` em `BudgetConfig`; rejeitar se prompt excede | **S1** |
| C-3 | **Cap em tokens de output (streaming)** | ❌ | upstream pode gerar saída ilimitada | injetar `max_tokens` no request antes de proxy se cliente não passar | **S1** |
| C-4 | **Runaway recursivo / agente** | N/A | não há agentic loop interno | — | — |
| C-5 | **Custo por unidade de valor** (custo / request, custo / tenant) | parcial | `/v1/economics`, `/v1/intelligence` mostra | métrica volátil (P-5) | persistir | S1 |
| C-6 | **Log ingestion cost** | N/A diretamente | logs JSON estruturados; volume depende de `log_level`; sem retention controllada por AION | documentar política de retention recomendada | S3 |
| C-7 | **Egress / network** | parcial | proxy → LLM externo; egress depende do volume; se cliente está em VPC sem peering, cobra muito | guia de deploy alerta sobre VPC peering com OpenAI/Anthropic se aplicável | S3 |
| C-8 | **Idle compute** | N/A | uvicorn 1 réplica é ~0.05 vCPU idle; ok | — | — |
| C-9 | **Cache hit rate medido** | ✅ | `/v1/cache/stats` ([observability.py:308-338](aion/routers/observability.py)) | bom | — |
| C-10 | **LLM token cost** | parcial | `cost_per_1k_*` em models.yaml ([config/models.yaml](config/models.yaml)) | ⚠ preços hardcoded sem timestamp/source; drift vs billing real (L-7) | adicionar `pricing_observed_at`, fonte; CI verifica drift contra API oficial | S2 |
| C-11 | **Database query cost** | N/A | sem DB próprio (Redis k-v) | — | — |
| C-12 | **Storage cost drift** | parcial | `AION_TELEMETRY_RETENTION_HOURS=168` (default 7 dias) ([config.py](aion/config.py)); buffer in-memory perde tudo ao restart | aceitável | — |
| C-13 | **Alertas de custo** | parcial | budget tem `alert_threshold` ([intelligence.py:82-86](aion/routers/intelligence.py)) | sem dono nomeado, sem dashboard de tendência cliente-facing | adicionar alerting webhook/integração e ownership policy no `BudgetConfig` | S2 |

### Achados Cost por severidade

| S | Itens |
|:---:|---|
| **S1** | C-2 (per-request cap), C-3 (output token cap em streaming), C-5 (custo por unidade volátil) |
| **S2** | C-10 (preços hardcoded), C-13 (alerting incomplete) |
| **S3** | C-6, C-7 |

### Promessa cost engineering vs evidência

- **Promessa:** "Cap de gasto por tenant via PUT /v1/budget/{tenant}" — ✅ implementada (diário/mensal). 
- **Promessa:** "AION economiza tokens via bypass" — ✅ medida tecnicamente, **mas a métrica é volátil**.
- **Gap:** "AION economiza dinheiro" → o cliente que perguntar "quanto economizei?" recebe um número que pode estar errado por:
  1. preços defasados no YAML;
  2. counters in-memory voláteis;
  3. `total_spend_usd` exibindo `cost_saved` como fallback (L-6).

**Recomendação cost engineering:** adicionar uma **trilha financeira** persistente — cada decisão (bypass/route/passthrough) emite registro com (tenant, timestamp, model, decision, prompt_tokens_estimate, completion_tokens_actual, cost_at_time, baseline_cost_at_time, pricing_source_id). Isso vira a fonte única de truth para `/v1/economics` e `/v1/intelligence/{tenant}/overview`. Sem isso, o produto não consegue **provar valor** (5ª Verdade).
