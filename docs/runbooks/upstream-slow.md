# LLM Provider Lento ou Indisponivel

## Severidade: P2 (um provider) / P1 (todos os providers)

## Sintomas

- Latencia de requests subindo (p95 > 5s)
- Circuit breaker abrindo para um ou mais providers
- Logs: `circuit_breaker_open`, `upstream_timeout`, `provider_error`
- `GET /metrics`: `aion_circuit_breaker_open{provider="X"} 1`
- Clientes recebendo 503 ou timeouts

## Impacto

| Cenario | Impacto |
|---------|---------|
| 1 provider lento | NOMOS redireciona para outros providers automaticamente |
| 1 provider fora | Circuit breaker abre, fallback chain ativa |
| Todos os providers lentos | Requests enfileiram, p95 sobe, possivel timeout |
| Todos os providers fora | Requests falham com 503/502 |

## Diagnostico

```bash
# 1. Status geral
curl -s http://localhost:8080/health | jq '.'

# 2. Metricas de circuit breaker
curl -s http://localhost:8080/metrics | grep circuit_breaker

# 3. Latencia por provider
curl -s http://localhost:8080/v1/stats | jq '.avg_latency_ms'

# 4. Eventos recentes (ver erros)
curl -s http://localhost:8080/v1/events?limit=20 | jq '.[] | select(.decision == "error")'

# 5. Status dos providers upstream
curl -s https://status.openai.com/api/v2/status.json | jq '.status'
```

## Remediacao

### Provider unico lento:

1. **Verificar status page do provider** (status.openai.com, status.anthropic.com)
2. **Forcar modelo alternativo via override:**

```bash
# Redirecionar tenant especifico para outro provider
curl -X PUT http://localhost:8080/v1/overrides \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant": "default", "overrides": {"cost_target": "fast"}}'
```

3. **Desabilitar modelo problematico no registry:**

```bash
# Toggle module off se necessario
curl -X PUT http://localhost:8080/v1/modules/nomos/toggle \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

### Todos os providers fora:

1. **Ativar SAFE_MODE** (bypass todos os modulos, requests falham rapido no proxy):

```bash
curl -X PUT http://localhost:8080/v1/killswitch \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason": "all_providers_down"}'
```

2. **Monitorar recovery** — circuit breaker recupera em 30s (configuravel via `AION_CIRCUIT_BREAKER_RECOVERY_SECONDS`)

3. **Desativar SAFE_MODE quando providers voltarem:**

```bash
curl -X DELETE http://localhost:8080/v1/killswitch \
  -H "Authorization: Bearer $ADMIN_KEY"
```

### Circuit breaker nao recuperando:

- Threshold: 5 falhas consecutivas (configuravel via `AION_CIRCUIT_BREAKER_THRESHOLD`)
- Recovery: 30s (configuravel via `AION_CIRCUIT_BREAKER_RECOVERY_SECONDS`)
- Se provider voltou mas circuit breaker nao recuperou, aguardar o recovery window

## Prevencao

- Configurar NOMOS com multiplos providers (OpenAI + Anthropic + Gemini)
- Fallback chain: se modelo primario falha, NOMOS usa proximo disponivel
- Monitorar `aion_circuit_breaker_open` com alerta
- Monitorar latencia p95 com alerta em > 5s
- Manter pelo menos 2 providers com API keys validas

## Escalacao

- P2: um provider fora, fallback funcionando
- P1: todos os providers fora, ou fallback chain esgotada
- Contato: time de infra + verificar status pages dos providers
