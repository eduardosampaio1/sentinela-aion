# AION Operations Runbook

Guia operacional para diagnosticar e resolver incidentes no AION em produção.

## Dashboards e endpoints operacionais

| URL | Descrição |
|---|---|
| `http://aion/health` | Status dos módulos e modo (normal/degraded) |
| `http://aion/ready` | Readiness probe (K8s) — 200 quando pipeline pronto |
| `http://aion/metrics` | Prometheus metrics (scraping) |
| `http://aion/v1/pipeline` | Topologia pre/post modules |
| `http://aion/v1/stats` | Stats agregadas por tenant |
| `http://aion/v1/events?limit=100` | Últimos eventos telemétricos |
| Jaeger UI | `http://jaeger:16686` |
| Prometheus | `http://prometheus:9090` |
| Grafana | `http://grafana:3030` (anon admin) |

## Alertas e diagnóstico

### `AionClassifierDegraded` — CRITICAL

**Sintoma**: `aion_classifier_degraded{replica="..."} == 1` no Prometheus.
**Causa**: embedding model não carregou (HF offline + cache ausente, ou OOM).
**Impacto**: bypass + risk classification desativados. PII + policy (regex) ainda funcionam.

```
# Diagnóstico
curl http://aion/health | jq '.estixe'
docker logs aion | grep -i embedding

# Fix
# 1. Verificar que o modelo está cacheado na imagem
docker exec aion ls /opt/hf-model

# 2. Se vazio: rebuild da imagem Docker
docker compose build aion

# 3. Restart
docker compose up -d --force-recreate aion
```

### `AionHighErrorRate` — WARNING

**Sintoma**: `rate(aion_errors_total[5m]) > 5`.
**Causa típica**: upstream LLM caiu, Redis indisponível, payload malformado.

```
# Diagnóstico
curl http://aion/v1/events?limit=20 | jq '.[] | select(.decision=="fallback")'

# Fix
# Se upstream caiu: circuit breaker já abre automaticamente.
# Se Redis caiu: AION continua em modo local (circuit breaker aplicado).
# Se request malformado: cliente está mandando body errado.
```

### `AionHighLatencyP95` — WARNING

**Sintoma**: `histogram_quantile(0.95, rate(aion_request_latency_seconds_bucket[5m])) > 0.5`.
**Causa típica**: cache cold (recém deploy), embedding CPU-bound, LB desbalanceado.

```
# Diagnóstico
curl http://aion/health | jq '.estixe.decision_cache'  # hit_rate
curl http://aion/metrics | grep classify_cache_hit_rate

# Fix
# 1. Warm-up automático: aguardar 1-2min pra cache encher.
# 2. Scale horizontal: adicionar replicas se traffic > capacidade.
# 3. Se classify_cache_hit_rate < 70%: review das queries em prod (talvez diversidade alta).
```

### `AionBlockRateSustained` — WARNING

**Sintoma**: >15% dos requests bloqueados por 5min.
**Causa típica**: ataque distribuído OU regra nova muito agressiva.

```
# Diagnóstico — ver o que está sendo bloqueado
curl http://aion/v1/events?limit=50 | jq '.[] | select(.decision=="block") | {reason:.metadata.detected_risk_category, input}'

# Fix
# Se ataque: deixar velocity detection apertar thresholds automaticamente.
# Se regra errada: /v1/estixe/intents/reload após fix no risk_taxonomy.yaml.
# Se emergência: POST /v1/killswitch (ativa SAFE_MODE — passthrough total).
```

### `AionReplicaDown` — CRITICAL

**Sintoma**: `up{job="aion",instance="aion1:8080"} == 0`.
**Causa**: container morreu ou OOM.

```
# Diagnóstico
docker ps -a | grep aion
docker logs aion1 --tail 100

# Fix
docker compose up -d aion1       # LB automaticamente retira do pool quando down.
```

## Procedimentos de mudança

### Hot-reload de intents/taxonomy (sem downtime)

```
# 1. Editar arquivos no volume montado
vim aion/aion/estixe/data/intents.yaml
vim aion/aion/estixe/data/risk_taxonomy.yaml

# 2. Reload sem restart
curl -X POST http://aion/v1/estixe/intents/reload \
  -H "Authorization: Bearer $ADMIN_KEY"

# Response:
# {"intents": 12, "examples": 80, "risk_categories": 8, "risk_seeds": 107}
```

### Override de threshold por tenant

```
# Pra ficar mais permissivo em 1 tenant específico:
curl -X PUT http://aion/v1/overrides \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "X-Aion-Tenant: client_a" \
  -d '{"estixe_thresholds": {"fraud_enablement": 0.85}}'

# Mais rigoroso:
curl -X PUT http://aion/v1/overrides \
  -H "X-Aion-Tenant: client_a" \
  -d '{"estixe_thresholds": {"fraud_enablement": 0.65}}'

# Reset
curl -X DELETE http://aion/v1/overrides -H "X-Aion-Tenant: client_a"
```

### Shadow mode para nova categoria

1. Adicionar categoria no `risk_taxonomy.yaml` com `shadow: true`
2. Reload: `POST /v1/estixe/intents/reload`
3. Monitorar `shadow_risk_category` em `/v1/events` por 7-14 dias
4. Se FP < 1% e TP > 60%: remover `shadow: true` e reload

### Killswitch de emergência

```
# Ativa SAFE_MODE: todos os modules bypassed, puro passthrough.
curl -X PUT http://aion/v1/killswitch \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -d '{"reason": "incident XYZ-123"}'

# Desativar depois:
curl -X DELETE http://aion/v1/killswitch
```

## Capacity planning

| Traffic | Recommendation |
|---|---|
| < 100 RPS | 2 replicas × 2GB |
| 100-500 RPS | 3 replicas × 2GB + nginx proxy_cache |
| 500-2000 RPS | 6 replicas × 2GB + nginx proxy_cache + Redis cluster |
| > 2000 RPS | Horizontal autoscaling (K8s HPA) + GPU inference (v2) |

Cada replica Python ~500 decisions/s no path slow (pipeline completo). Com nginx
proxy_cache (FASE 7), queries repetidas são servidas em <1ms pelo LB sem tocar
AION. Escala efetiva: **~10k-50k decisions/s por nginx** em modo `proxy_cache`.

## Backup & disaster recovery

| Item | Strategy |
|---|---|
| `.runtime/overrides.json` | rsync diário pra S3 (fallback sem Redis) |
| `intents.yaml`, `risk_taxonomy.yaml` | versionado em git |
| Redis data | `redis-cli --rdb /backup/dump-$(date +%F).rdb` diário |
| Prometheus data | retention configurada pra 7 dias (ajustar conforme necessário) |

## Contatos

- Incident response: `#aion-incidents` (Slack)
- Slow burn issues: `#aion-eng`
- Security: security@company.com
