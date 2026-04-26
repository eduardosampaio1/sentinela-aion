# Roteiro da POC — AION Sentinela

## Objetivo

Validar que o AION funciona como camada de controle entre a aplicação do cliente e o LLM, sem alterar o comportamento existente — e que os ganhos (custo, segurança, visibilidade) são mensuráveis.

---

## Fase 1 — Setup (Dia 1)

**Meta:** AION rodando no ambiente do cliente, recebendo tráfego real ou simulado.

```bash
git clone https://github.com/eduardosampaio1/sentinela-aion.git
cd sentinela-aion
pip install -e .
python start.py
```

Verificação mínima:
```bash
curl http://localhost:8080/health
# Esperado: {"status": "ok", "modules": {...}}
```

Troca o `base_url` da aplicação:
```python
# Antes
client = OpenAI(api_key="sk-...")

# Depois (zero mudança no restante do código)
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
| `pii_detected` | Quantos requests tinham CPF, email, chave de API expostos |
| `cost_saved` | Estimativa de tokens economizados por bypass |
| `decisions` | Distribuição: BYPASS / CONTINUE / BLOCK |

Critério de saúde: latência adicionada pelo AION < 20ms no P95 (ver `/v1/stats`).

---

## Fase 3 — Validação (Dias 8–14)

**Meta:** Confirmar que o AION não quebrou nada e que os números fazem sentido.

Checklist:
- [ ] Respostas da aplicação idênticas às sem o AION (testar 10 casos reais)
- [ ] Nenhum falso positivo crítico em PII (revisar `/v1/audit`)
- [ ] `bypass_rate` > 0% (se zero, os intents não estão calibrados)
- [ ] Latência P95 aceitável

Se tudo OK → aprovar calibração:
```bash
curl -X PUT http://localhost:8080/v1/calibration/seu-tenant \
  -H "Content-Type: application/json" \
  -d '{"promote": true}'
```

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
curl -X PUT http://localhost:8080/v1/killswitch
# AION passa tudo direto, sem processar
```

Para desativar:
```bash
curl -X DELETE http://localhost:8080/v1/killswitch
```

---

## Contatos e suporte

- Repositório: https://github.com/eduardosampaio1/sentinela-aion
- Runbook operacional: `docs/RUNBOOK.md`
- Checklist de produção: `docs/PRODUCTION_CHECKLIST.md`
