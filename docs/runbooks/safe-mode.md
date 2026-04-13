# SAFE_MODE Ativado

## Severidade: P2 (se nao intencional)

SAFE_MODE (kill switch) desabilita todos os modulos do pipeline. Requests passam direto para o LLM sem analise, sem PII guard, sem routing, sem compressao.

## Sintomas

- `GET /health` retorna `mode: safe`
- `GET /v1/killswitch` retorna `active: true, reason: "..."`
- Todos os modulos listados como `disabled` no health check
- Nenhum bypass ou block acontecendo (tudo passa direto)
- Telemetria mostra `decision: passthrough` para 100% dos requests
- PII nao esta sendo detectada/mascarada

## Impacto

| Feature | Normal | SAFE_MODE |
|---------|--------|-----------|
| PII detection | Ativo | **DESATIVADO** |
| Policy engine | Ativo | **DESATIVADO** |
| Intent bypass | Ativo | **DESATIVADO** |
| Model routing | Ativo | **DESATIVADO** |
| Prompt compression | Ativo | **DESATIVADO** |
| Rate limiting | Ativo | Ativo (middleware, nao modulo) |
| Auth/RBAC | Ativo | Ativo |
| Audit trail | Ativo | Ativo |

## Diagnostico

```bash
# 1. Verificar status do kill switch
curl -s http://localhost:8080/v1/killswitch \
  -H "Authorization: Bearer $ADMIN_KEY" | jq '.'

# 2. Verificar quem ativou (audit trail)
curl -s http://localhost:8080/v1/audit?limit=50 \
  -H "Authorization: Bearer $ADMIN_KEY" | jq '.[] | select(.action == "killswitch")'

# 3. Verificar se foi ativado via env (AION_SAFE_MODE=true)
docker exec aion env | grep SAFE_MODE

# 4. Health check completo
curl -s http://localhost:8080/health | jq '.'
```

## Remediacao

### Se ativado intencionalmente:

Verificar com quem ativou se ja pode desativar.

### Se ativado acidentalmente ou nao autorizado:

1. **Desativar via API:**

```bash
curl -X DELETE http://localhost:8080/v1/killswitch \
  -H "Authorization: Bearer $ADMIN_KEY"
```

2. **Verificar que modulos voltaram:**

```bash
curl -s http://localhost:8080/health | jq '.modules'
```

3. **Se ativado via env (`AION_SAFE_MODE=true`):**

```bash
# Remover variavel e reiniciar
docker-compose down
# Editar .env: AION_SAFE_MODE=false
docker-compose up -d
```

### Se ativado por acesso nao autorizado:

1. Verificar audit trail para identificar a key usada
2. Rotacionar admin key (ver runbook: admin-key-leaked.md)
3. Desativar SAFE_MODE

## Prevencao

- Restringir acesso a admin keys (nao compartilhar em canais abertos)
- Monitorar ativacao de SAFE_MODE com alerta
- Audit trail registra quem ativou e quando
- Nao usar `AION_SAFE_MODE=true` em producao (apenas em emergencias)

## Escalacao

- P3 se ativado intencionalmente e controlado
- P2 se ativado sem autorizacao (possivel comprometimento de admin key)
- P1 se PII esta vazando por falta de guardrails
