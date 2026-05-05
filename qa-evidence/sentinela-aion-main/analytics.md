# Fase 9 — Analytics, Métricas e Prova de Valor

## 9.1 Auditoria de Eventos

`TelemetryEvent` ([telemetry.py:109-142](aion/shared/telemetry.py)):

| Campo | Presente | Comentário |
|---|:---:|---|
| nome consistente (`event_type`) | ✅ | mas sem registry/enum oficial |
| propriedades úteis | ✅ | `decision`, `model_used`, `tokens_saved`, `cost_saved`, `latency_ms` |
| boundary id (`tenant`) | ✅ | ok |
| ator (`actor_id`) | parcial | só em audit entries quando `trusted_proxy` |
| `session_id` | parcial | em session_audit, não em telemetria geral |
| timestamp | ✅ | epoch float |
| timezone explícito | ❌ | não há ISO 8601 + tz; somente epoch |
| source | ❌ | sem; usa `module` |
| environment (`prod`/`stg`/`dev`) | ❌ | sem; só `replica_id` |
| correlation_id | ✅ | `request_id` propagado |
| versão da feature | ❌ | nem `feature_version`, nem `model_prompt_hash`, nem `policy_version` |
| resultado da ação | ✅ | em `decision` |
| motivo de falha | parcial | em `event.metadata.block_reason` etc. |
| unidade de medida | ✅ | tokens, USD, ms |
| origem do dado | parcial | `replica_id`, `module` |
| dispara uma única vez | parcial | sem garantia idempotente cross-replica |
| dispara depois da operação concluir | ✅ | emit chamado após pipeline |
| sem PII indevida | ❌ | **`event.data["input"]` carrega texto cru** (SEC-6) |

## 9.2 Auditoria de Funil

| Funil | Mensurável? | Nota |
|---|:---:|---|
| **Ativação (primeiro valor)**: cliente liga AION → primeiro request → primeiro bypass → primeira economia documentada | ❌ | sem evento "first_bypass_for_tenant", sem "time_to_first_value" |
| **Adoção módulos**: ESTIXE → NOMOS → METIS → cache | parcial | counters por decision; sem segmentação adoção |
| **Comercial**: trial → POC → contrato | N/A | fora do escopo do produto core |
| **Bypass success rate (intent)** | ✅ | NEMOS IntentMemory tem `bypass_success_rate` ([intelligence.py:231](aion/routers/intelligence.py)) |
| **Block rate** | ✅ | counter |
| **Time entre etapas** | ❌ | sem |
| **Conversão por etapa** | parcial | bypass_success_rate é proxy |
| **Segmentação por boundary, perfil, plano** | ❌ | métricas Prometheus sem label `tenant`; intelligence só vê por tenant individual |
| **Antes/depois** | parcial | NEMOS baselines snapshot horário, mas sem capacidade de "comparar adoção pós-feature flip" |

## 9.3 Métricas de Produto

- ✅ Total requests, bypass total, block total, errors total
- ✅ Latency p50/p95/p99 (janela curta — 1000 amostras)
- ✅ Cache hit rate
- ✅ ESTIXE classifier degraded gauge
- ❌ Tempo até primeiro valor (TTFV)
- ❌ DAU / Tenants ativos por dia
- ❌ Adoção por feature (% tenants usando behavior dial, % usando overrides etc.)
- ❌ Profundidade de uso (turns / session, tenants com >X requests/dia)
- ❌ Frequência de uso por tenant (cohort)

## 9.4 Métricas de Negócio (vs promessas declaradas)

Tabela de checagem das promessas (Pré-0):

| Promessa | Métrica que prova | Existe? | Cálculo | Gap | Severidade |
|---|---|:---:|---|---|:---:|
| Isolamento multi-tenant | "0 vazamentos detectados", "operadores autorizados ao seu tenant" | ❌ | — | sem métrica de "tenant boundary violation attempt"; sem evidência | **S1** |
| Licença Ed25519 offline | "0 phone-home requests" | ✅ qualitativa | trust_guard registra offline | — | — |
| Audit hash-chained HMAC | "100% entries signed" / "0 chain breaks" | parcial | exposed via compliance summary `audit_trail_signed` boolean (env-derived, não real) | métrica deveria ser % signed dentro do chain | S2 |
| Bypass zero-token | "tokens_saved" e "llm_calls_avoided" | ✅ | counters | volátil (P-5) | **S1** |
| Bloqueio prompt injection / PII | "block_total", "pii_intercepted" | parcial | counter total + recent_events scan ([intelligence.py:54-59](aion/routers/intelligence.py)) | sem baseline FP/TP, sem "PII intercepted by category" persistente | **S2** |
| NOMOS routing inteligente | "savings vs default model" | parcial | `estimated_without_aion - total_spend` | preços hardcoded (L-7), volátil | **S1** |
| METIS compressão | "tokens_compressed", "compression_ratio" | ❌ | counter `tokens_before` vs `tokens_after` existe internamente mas não exposto | métrica fantasma | S2 |
| LGPD `/v1/data/{tenant}` | "deletions performed", "retention compliance" | parcial | log apenas | sem trail próprio LGPD | S2 |
| Budget cap por tenant | "% tenants over 80% cap", "blocks por cap" | parcial | `/v1/intelligence/{tenant}/overview.budget` mostra single tenant | sem agregado fleet-wide | S3 |
| PII nunca sai do ambiente | — | ❌ | `event.data.input` vaza para ARGOS (opt-in) (SEC-6) | promessa contradita | **S1** |
| 702+ testes 0 falhas | grep funções `def test_` | ❌ | 201 funções (L-1) | promessa contradita | S2 |
| Performance p95 < 500ms | exposto em Prometheus | ✅ | sample window curto | não validável neste audit (sem stress run) | — |
| Decisão explicável | `/v1/explain` | parcial | só dentro do buffer (L-8) | promessa contradita em escala | **S1** |

## 9.5 Métricas Executivas

`/v1/intelligence/{tenant}/overview` ([intelligence.py:99-122](aion/routers/intelligence.py)):

- `security.requests_blocked`, `pii_intercepted`, `top_block_reason` ✓ úteis
- `economics.total_spend_usd`, `estimated_without_aion_usd`, `savings_usd`, `savings_pct`, `tokens_saved`, `top_model_used` ✓ apresentação executiva
- `intelligence.requests_processed`, `bypass_rate`, `avg_latency_ms`, `module_maturity`
- `budget` (cap, today_spend, alert_active)

**Problemas executivos sérios:**

1. ❌ `total_spend_usd` cai em fallback `cost_saved` quando NEMOS sem dados (L-6). **Mistura conceitos opostos**.
2. ❌ `cost_saved` volátil (L-5) → "savings_usd" pode regredir após restart, gerando reuniões com perguntas embaraçosas.
3. ❌ `estimated_without_aion_usd` baseado em preços hardcoded (L-7) sem fonte rastreável.
4. ❌ Sem comparação **antes/depois implantação AION** — não há "baseline_pre_aion_30d" para validar.

## 9.6 Taxonomia

- `event_type`, `module`, `decision` são strings livres em código.
- Sem registry oficial (ex: `aion/shared/event_taxonomy.py` que enumera eventos válidos).
- Risco: dois lugares emitem `event_type="bypass_decision"` vs `event_type="bypass"`.

Recomendação: criar `aion/shared/events.py` com Enum + dataclasses por evento; CI valida que telemetry só emite eventos do registry.

## 9.7 Qualidade dos Dados

| Aspecto | Status |
|---|---|
| Evento duplicado | parcial — Redis cross-replica usa lista; sem dedup explícita |
| Evento perdido | ⚠ in-memory deque maxlen=10.000; perde em alto volume |
| Timestamp/timezone | ⚠ epoch float; sem tz |
| Métrica calc na camada cliente | ❌ não — backend calcula |
| Métrica manipulável | parcial — operator com chave admin pode bater PUT em overrides; mas counters são append-only |
| Schema | parcial — `schema_version: "1.0"` no event; sem JSON Schema externo |
| Validação | parcial — Pydantic em request/response, mas não em events |
| Versionamento de métricas | ❌ |
| Documentação | parcial |
| Ownership | ❌ sem `metric_owner` campo |
| Janela temporal | ❌ "tokens_saved_total" desde quando? |
| Baseline | parcial NEMOS |
| Outlier handling | ❌ |
| Denominador ambíguo | ⚠ "bypass_rate = bypasses / total_requests" — mas total_requests é all replicas? local? |

## 9.8 Dashboards e Decisão

`/v1/intelligence/{tenant}/overview` responde:

| Pergunta executiva | Resposta? |
|---|---|
| O que aconteceu? | parcial |
| Por que aconteceu? | ❌ (top_block_reason é proxy, não causa raiz) |
| Qual o impacto? | parcial (savings_pct) |
| O que devo fazer? | ❌ (sem `recommended_actions` de fato — `/v1/recommendations` existe mas separado) |
| Qual evidência sustenta? | ❌ (sem links rastreáveis aos eventos) |
| Qual risco se ignorar? | ❌ |

`aion-console` (Next.js): páginas mostram dados reais do backend (esperado), mas a robustez visual depende dos endpoints — herdam todos os problemas acima.

## 9.9 Experimentos

| Capacidade | Status |
|---|---|
| Feature flags | parcial (`AION_ESTIXE_ENABLED`, `AION_NOMOS_ENABLED` etc.) |
| A/B testing | ❌ |
| Cohort | ❌ |
| Segmentação por boundary | parcial (NEMOS por tenant) |
| Comparar antes/depois | parcial (baselines) |
| Tracking de versão | parcial (build_id no manifest); sem feature_version per request |
| Tracking de rollout | ❌ |
| Métricas por variante | ❌ |
| Rollback observável | parcial (kill switch) |
| Saber se uma mudança melhorou ou piorou | ❌ |

**Shadow Mode** (categoria de risco em observação) é uma forma simples de experimento, mas não é A/B framework.

## 9.10 Bloqueios Automáticos de Analytics

| Critério | Verifica? | Resultado |
|---|:---:|---|
| Produto sem eventos críticos | — | ✅ tem |
| Dashboard exec com dado mockado | — | ⚠ `cost_saved` volátil (semi-mock) |
| Promessa de economia sem métrica de economia | — | ⚠ tem métrica volátil + preços hardcoded |
| Promessa de qualidade sem métrica | — | parcial (block rate, FP rate não medido) |
| Promessa de confiança sem evidência | — | ⚠ audit chain forjável sem secret |
| Fluxo principal sem tracking | — | ✅ tem |
| Métricas calculadas inconsistentes | — | ⚠ `cost_saved` em 2 lugares + `total_spend_usd` fallback errado |
| Evento sem boundary id | — | ✅ tem |
| Evento sem correlation | — | ✅ tem |
| Analytics só na camada cliente para métrica crítica | — | ❌ backend calcula ✓ |
| Dados de negócio sem auditoria | — | ⚠ |
| Recomendação sem medição de aceite/rejeição | — | ⚠ `/v1/recommendations` existe, sem feedback loop |
| POC sem capacidade de provar valor | — | ⚠ depende de cliente externalmente computar |
| Onboarding sem funil mensurável | — | ⚠ |
| Fluxo de ativação sem medição | — | ❌ falta |
| Dashboard sem fonte real | — | ⚠ fonte real, mas volátil |
| ROI sem fórmula | — | ⚠ fórmula `estimated_without_aion - total_spend` é simples mas insumos errados |
| Score sem explicabilidade | — | ⚠ `module_maturity` sem explicar critério; recommendations sem mostrar evidência subjacente |
| Métrica executiva sem evidência | — | ⚠ |

## 9.11 Veredito Analítico

**`PARCIALMENTE MENSURÁVEL` com forte tendência a `CEGO PARA VALOR`.**

- **Forte em:** instrumentação técnica (eventos, counters, audit chain, Prometheus, NEMOS).
- **Fraco em:** durabilidade dos dados executivos, baseline de preços com fonte, funil de ativação, comparações antes/depois, segmentação fleet-wide, taxonomia de eventos versionada.
- **Promessas de economia** são apresentadas em telas executivas, mas:
  - usam preços que podem estar defasados;
  - resetam a cada restart;
  - misturam conceitos opostos em fallback;
  - não têm baseline pré-AION para comparação real.

> "Sem analytics confiável, o produto pode até funcionar, mas não consegue provar que importa."
