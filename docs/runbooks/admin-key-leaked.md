# Admin Key Comprometida

## Severidade: P1

Uma admin key comprometida permite acesso total ao control plane: ativar SAFE_MODE, alterar overrides, deletar dados de tenant (LGPD), recarregar policies, e toggle de modulos.

## Sintomas

- Acoes nao autorizadas no audit trail
- SAFE_MODE ativado sem explicacao
- Overrides ou behavior dial alterados inesperadamente
- Dados de tenant deletados sem solicitacao
- Policies ou intents recarregados sem deploy

## Diagnostico

```bash
# 1. Verificar audit trail para acoes recentes com a key suspeita
curl -s http://localhost:8080/v1/audit?limit=100 \
  -H "Authorization: Bearer $ADMIN_KEY" | jq '.'

# 2. Filtrar acoes criticas
curl -s http://localhost:8080/v1/audit?limit=100 \
  -H "Authorization: Bearer $ADMIN_KEY" | \
  jq '.[] | select(.action == "killswitch" or .action == "data_delete" or .action == "override_set")'

# 3. Verificar status atual
curl -s http://localhost:8080/health | jq '.'
curl -s http://localhost:8080/v1/killswitch \
  -H "Authorization: Bearer $ADMIN_KEY" | jq '.'
```

## Remediacao Imediata

### 1. Rotacionar admin key

```bash
# Gerar nova key
NEW_KEY=$(openssl rand -hex 32)

# AION suporta multiplas keys (rotacao sem downtime):
# AION_ADMIN_KEY="new_key:admin,old_key:admin"

# Atualizar env com nova key (manter old temporariamente)
export AION_ADMIN_KEY="${NEW_KEY}:admin,${OLD_KEY}:admin"

# Reiniciar AION
docker-compose restart aion

# Verificar que nova key funciona
curl -s http://localhost:8080/health \
  -H "Authorization: Bearer ${NEW_KEY}" | jq '.'

# Apos confirmar, remover key antiga
export AION_ADMIN_KEY="${NEW_KEY}:admin"
docker-compose restart aion
```

### 2. Reverter acoes maliciosas

```bash
# Desativar SAFE_MODE se foi ativado
curl -X DELETE http://localhost:8080/v1/killswitch \
  -H "Authorization: Bearer ${NEW_KEY}"

# Verificar e restaurar overrides
curl -s http://localhost:8080/v1/overrides \
  -H "Authorization: Bearer ${NEW_KEY}" | jq '.'

# Restaurar behavior dial se alterado
curl -X DELETE http://localhost:8080/v1/behavior \
  -H "Authorization: Bearer ${NEW_KEY}"

# Recarregar policies (restaurar originais)
curl -X POST http://localhost:8080/v1/estixe/policies/reload \
  -H "Authorization: Bearer ${NEW_KEY}"
```

### 3. Verificar dados deletados

```bash
# Se DELETE /v1/data/{tenant} foi chamado, dados foram apagados
# Verificar no audit trail quais tenants foram afetados
curl -s http://localhost:8080/v1/audit?limit=100 \
  -H "Authorization: Bearer ${NEW_KEY}" | \
  jq '.[] | select(.action == "data_delete")'
```

### 4. Investigar origem do vazamento

- Verificar repositorios Git (key commitada?)
- Verificar logs de CI/CD
- Verificar comunicacoes (Slack, email)
- Verificar acessos ao servidor/container

## Prevencao

- Nunca commitar admin keys em repositorios
- Usar secret manager (Vault, AWS Secrets Manager, etc.)
- Rotacionar keys periodicamente (mensal)
- Usar keys diferentes por ambiente (dev/staging/prod)
- Monitorar audit trail com alerta em acoes criticas
- RBAC: usar role `operator` em vez de `admin` quando possivel
- Rate limit em endpoints admin (ja implementado: 10/min)

## Escalacao

- P1 sempre — comprometimento de admin key e incidente de seguranca
- Notificar: time de seguranca, engenharia, e stakeholders dos tenants afetados
- Se dados de tenant foram deletados: notificar tenant e avaliar obrigacoes LGPD
