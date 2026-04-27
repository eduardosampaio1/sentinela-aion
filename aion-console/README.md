# AION Console

Console de observabilidade e auditoria do AION — plataforma de decisão para sistemas de IA conversacional.

---

## O que é o AION

O AION avalia cada requisição do usuário antes de qualquer chamada ao LLM. Em menos de 50ms ele retorna um **Decision Contract** dizendo se a mensagem deve ser respondida localmente (bypass), roteada para qual modelo, ou bloqueada por segurança — com razão auditável e custo estimado evitado.

```
App do cliente
  → AION /v1/decide
  → Decision Contract
  → App do cliente executa LLM com suas próprias credenciais
```

O AION não recebe chave de LLM, não executa chamadas externas e não envia dados para fora do ambiente do cliente.

---

## Modos de POC

| Modo | Status | Descrição |
|---|---|---|
| **POC Decision-Only** | Recomendado | AION decide, cliente executa. Sem chave LLM, sem callout externo. |
| **POC Transparent** | Alternativa | AION intercepta como proxy. Cliente troca só `base_url`. Requer chave LLM. |
| **Shadow Mode** | Fase 2 | Políticas em observação paralela. Telemetria opt-in. Pós-POC. |
| **Full Version** | Fase 3 | NOMOS ML, METIS, Collective. Pós-validação. |

A POC não inclui Shadow Mode, Collective real, telemetria externa, Supabase ou Render da Baluarte.

---

## Início rápido

```bash
# 1. Configurar ambiente
cp .env.poc-decision.example .env

# 2. Subir stack (Runtime + Redis + Console)
docker compose -f docker-compose.poc-decision.yml up -d

# 3. Verificar saúde
curl http://localhost:8080/health

# 4. Primeira decisão
curl -s -X POST http://localhost:8080/v1/decide \
  -H "Content-Type: application/json" \
  -d '{"input": "Oi, tudo bem?", "session_id": "demo-001"}' | jq .

# 5. Abrir console
open http://localhost:3000
```

Veja [`docs/quickstart.md`](docs/quickstart.md) para o guia completo.

---

## Console

O console responde as 11 perguntas que qualquer stakeholder vai fazer:

1. O AION está rodando?
2. Em qual modo?
3. Telemetria está ligada ou desligada?
4. Collective está ativo ou é só catálogo?
5. Quantas decisões tomou?
6. Quantos bypasses fez?
7. Quantos riscos bloqueou?
8. Por que decidiu bloquear/bypassar/continuar?
9. Quanto potencialmente economizou?
10. Onde está o audit?
11. Dá para exportar evidência?

### Stack do console

- Next.js 15 + React 18 + TypeScript
- TailwindCSS + shadcn/ui
- TanStack Query — estado de servidor
- Supabase JS SDK — autenticação (console, não runtime)

### Rodar em desenvolvimento

```bash
npm install
npm run dev
# http://localhost:3000
```

---

## Documentação

| Documento | Descrição |
|---|---|
| [`docs/POC_SCOPE.md`](docs/POC_SCOPE.md) | Linha de corte oficial — o que entra e o que fica fora da POC |
| [`docs/roteiro-poc.md`](docs/roteiro-poc.md) | Roteiro prático de demo e validação |
| [`docs/quickstart.md`](docs/quickstart.md) | Setup em 5 minutos |

---

## Linha de corte oficial

> **POC não é o AION completo. POC é o menor AION capaz de provar decisão, economia, risco e auditabilidade.**

Veja [`docs/POC_SCOPE.md`](docs/POC_SCOPE.md) para a tabela completa, checklist POC Ready e linha do tempo de adoção.
