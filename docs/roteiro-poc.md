# Roteiro da POC — AION Sentinela

## Objetivo

Validar que o AION funciona como camada de controle entre a aplicação do cliente e o LLM, sem alterar o comportamento existente — e que os ganhos (custo, segurança, visibilidade) são mensuráveis.

---

## Escolha o modo de POC

| | POC Decision-Only | POC Transparent |
|---|---|---|
| **Recomendado para** | Banco, telecom, enterprise restritivo | Integração acelerada |
| **AION recebe chave do LLM?** | **Não** | Sim |
| **Fricção com CISO/jurídico** | Mínima | Média |
| **Mudança na app** | Chamar `/v1/decide` antes do LLM | Trocar `base_url` |
| **Compose file** | `docker-compose.poc-decision.yml` | `docker-compose.poc-transparent.yml` |

**Recomendação para primeiro contato:** comece pelo Decision-Only. O cliente prova o valor do AION sem compartilhar credenciais do LLM. Após aprovação interna, a migração para Transparent é uma mudança de `.env`.

---

## Fase 1 — Setup (Dia 1)

**Meta:** AION rodando no ambiente do cliente, recebendo tráfego real ou simulado.

### Track A — POC Decision-Only (recomendado)

```bash
curl -O https://raw.githubusercontent.com/eduardosampaio1/sentinela-aion/develop/docker-compose.poc-decision.yml
printf "AION_LICENSE=<jwt-fornecido-pela-baluarte>\nAION_ADMIN_KEY=chave-poc:admin\n" > .env
docker compose -f docker-compose.poc-decision.yml up -d
```

Verificação mínima:
```bash
curl http://localhost:8080/health
# → {"status":"ok","aion_mode":"poc_decision","executes_llm":false,...}
```

Integração na app do cliente:
```python
# Antes de chamar o LLM, consultar o AION
resp = httpx.post("http://localhost:8080/v1/decide",
    headers={"X-Aion-Tenant": "meu-tenant"},
    json={"model": "gpt-4o", "messages": messages},
)
if resp.json()["decision"] == "continue":
    # chamar o LLM com as próprias credenciais do cliente
    pass
```

### Track B — POC Transparent (opcional)

```bash
curl -O https://raw.githubusercontent.com/eduardosampaio1/sentinela-aion/develop/docker-compose.poc-transparent.yml
cat > .env <<EOF
AION_LICENSE=<jwt-fornecido-pela-baluarte>
AION_ADMIN_KEY=chave-poc:admin
OPENAI_API_KEY=sk-...
EOF
docker compose -f docker-compose.poc-transparent.yml up -d
```

Integração na app do cliente (zero-code):
```python
# Antes
client = OpenAI(api_key="sk-...")

# Depois (única mudança)
client = OpenAI(api_key="sk-...", base_url="http://localhost:8080/v1")
```

---

## Fase 2 — Observação Local (Dias 2–7)

**Meta:** Acumular dados reais sem interferir em nada.

> **Nota:** Esta fase é totalmente local. Nenhum dado sai do ambiente do cliente.
> Toda a observação acontece via dashboard interno (`/v1/stats`, `/v1/events`).
> "Shadow Mode" no contexto do AION Baluarte é uma fase separada, opt-in, que requer
> DPA assinado — não faz parte deste roteiro de POC.

O que observar no dashboard (`http://localhost:3001`):

| Métrica | O que significa |
|---------|----------------|
| `bypass_rate` | % de requests que o AION respondeu sem chamar o LLM |
| `block_rate` | % bloqueados por policy, PII ou guardrail |
| `pii_detected` | Quantos requests tinham CPF, email, chave de API expostos |
| `cost_saved` | Estimativa de tokens economizados por bypass |
| `decisions` | Distribuição: BYPASS / CONTINUE / BLOCK |

Critério de saúde: latência adicionada pelo AION < 20ms no P95 (ver `/v1/stats`).

---

## Fase 3 — Validação (Dias 8–14)

**Meta:** Confirmar que o AION não quebrou nada e que os números fazem sentido.

Checklist:
- [ ] Respostas da aplicação idênticas às sem o AION (testar 10 casos reais)
- [ ] Nenhum falso positivo crítico em PII (revisar `/v1/events`)
- [ ] `bypass_rate` > 0% (se zero, os intents não estão calibrados)
- [ ] Latência P95 aceitável
- [ ] Nenhum erro 5xx introduzido pelo AION

---

## O que define sucesso da POC

| Critério | Meta mínima |
|----------|-------------|
| Bypass rate | ≥ 5% das requisições |
| PII detectado | ≥ 1 ocorrência real (valida o módulo) |
| Latência adicionada | < 30ms P95 |
| Zero quebras | Nenhum erro 5xx introduzido pelo AION |
| Visibilidade | Time consegue ver o que está acontecendo em tempo real |

---

## Rollback instantâneo

Se algo der errado, ative o safe mode — o AION vira passthrough transparente:

```bash
curl -X PUT http://localhost:8080/v1/killswitch \
  -H "Authorization: Bearer chave-poc"
# AION passa tudo direto, sem processar

# Para desativar:
curl -X DELETE http://localhost:8080/v1/killswitch \
  -H "Authorization: Bearer chave-poc"
```

---

## Próximos passos após POC aprovada

| Etapa | O que é |
|-------|---------|
| POC Transparent | Migrar de Decision-Only para proxy completo (se ainda não foi) |
| Calibração de intents | Adicionar intents específicos do domínio do cliente |
| Redis do cliente | Apontar para Redis de produção do cliente |
| Shadow Mode | Fase opt-in — requer DPA assinado com Baluarte |
| Collective | Catálogo editorial de policies — lifecycle administrativo |

---

## Contatos e suporte

- Repositório: https://github.com/eduardosampaio1/sentinela-aion
- Quickstart: `docs/quickstart.md`
- Guia de integração: `docs/poc-integration-guide.md`
- Checklist de produção: `docs/PRODUCTION_CHECKLIST.md`
