# Redis Indisponivel

## Severidade: P3 (degradado, nao critico)

AION funciona sem Redis — o fallback local e automatico. Porem, rate limiting, audit trail e overrides per-tenant perdem persistencia e consistencia entre replicas.

## Sintomas

- Logs: `redis_connection_failed` ou `redis_timeout`
- `GET /health` retorna `redis_connected: false`
- Rate limiting funciona mas com contagem per-instance (nao global)
- Overrides per-tenant nao propagam entre replicas
- Audit trail apenas em memoria (perde ao reiniciar)

## Impacto

| Feature | Com Redis | Sem Redis (fallback) |
|---------|-----------|---------------------|
| Rate limiting | Global (sorted set sliding window) | Per-instance (dict local) |
| Audit trail | Persistido (list per tenant) | In-memory (deque 10K, perde ao restart) |
| Overrides | Persistidos (hash per tenant) | In-memory (perde ao restart) |
| Behavior Dial | Persistido | In-memory |
| Pipeline core | Sem impacto | Sem impacto |

## Diagnostico

```bash
# 1. Verificar status do Redis
curl -s http://localhost:8080/health | jq '.redis_connected'

# 2. Testar conectividade Redis diretamente
redis-cli -u $REDIS_URL ping

# 3. Verificar logs do AION
docker logs aion 2>&1 | grep -i redis

# 4. Verificar metricas
curl -s http://localhost:8080/metrics | grep redis
```

## Remediacao

### Se Redis voltou mas AION nao reconectou:

AION reconecta automaticamente (lazy reconnect). Force uma operacao que usa Redis:

```bash
# Qualquer request que toca rate limit forca reconexao
curl -H "Authorization: Bearer $ADMIN_KEY" http://localhost:8080/v1/stats
```

### Se Redis esta definitivamente fora:

1. AION continua operando normalmente com fallback local
2. Overrides e Behavior Dial configurados via API serao perdidos ao restart
3. Re-aplicar overrides apos Redis voltar:

```bash
curl -X PUT http://localhost:8080/v1/overrides \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant": "acme", "overrides": {"key": "value"}}'
```

### Se ha multiplas replicas (rate limit inconsistente):

- Rate limit per-instance pode permitir mais requests que o limite global
- Mitigacao: reduzir limites temporariamente (ex: de 100/min para 50/min per-instance)

## Prevencao

- Monitorar Redis com alerta em latencia > 100ms e conexao perdida
- Redis Sentinel ou Cluster para HA
- Definir `REDIS_URL` com timeout curto (2s) para failover rapido
- Testar periodicamente: `redis-cli -u $REDIS_URL ping`

## Escalacao

- P3 se uma replica, P2 se multiplas replicas (rate limit inconsistente)
- Nao escalar para P1 — AION funciona sem Redis
