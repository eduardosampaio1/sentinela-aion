# AION — Motor Realtime do Sentinela

Proxy gateway OpenAI-compatible que controla a IA em tempo real. Tres modulos independentes:

- **ESTIXE** — controla, bloqueia, bypassa (Zero-Token Response Engine)
- **NOMOS** — decide rota, escolhe modelo (AI Routing Intelligence)
- **METIS** — otimiza prompt e resposta (Behavior Dial)

## Quick Start

```bash
# 1. Clone e instale
cd aion
pip install -e .

# 2. Configure
cp .env.example .env
# Edite .env com sua API key do LLM

# 3. Rode
aion
# ou: python -m aion.cli
```

AION roda em `http://localhost:8080`. Aponte seu app para ele como proxy:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",  # AION como proxy
    api_key="sua-key",
)
```

## Quick Start com Docker

> **Licença obrigatória.** O AION não inicia sem uma licença válida.
> Coloque o arquivo `aion.lic` (fornecido pela Baluarte) na mesma pasta do `docker-compose.yml`,
> ou defina `AION_LICENSE=<jwt>` no `.env`.

### POC Decision-Only — recomendado para banco, telecom e enterprise restritivo

AION decide (bloqueia / bypass / aprova). Sua app chama o LLM com suas próprias credenciais.
**AION não recebe credencial de LLM.**

```bash
# .env mínimo
printf "AION_ADMIN_KEY=chave-poc:admin\nAION_SESSION_AUDIT_SECRET=$(openssl rand -hex 32)\n" > .env
# coloque aion.lic na mesma pasta
docker compose -f docker-compose.poc-decision.yml up -d
```

Testar:
```bash
curl -s http://localhost:8080/v1/decide \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Olá"}]}' | jq .
# → {"decision":"bypass","bypass_response":"Olá! Como posso ajudar?","latency_ms":1.8}
```

### POC Transparent — opcional, integração acelerada

AION intercepta e executa a chamada ao LLM. Cliente troca apenas o `base_url`.
Requer credencial do LLM. Discuta com CISO antes em ambientes restritivos.

```bash
# .env com chave admin + credencial do LLM
cp .env.example .env   # preencher AION_ADMIN_KEY, OPENAI_API_KEY, AION_SESSION_AUDIT_SECRET
docker compose -f docker-compose.poc-transparent.yml up -d
```

Verificar: `curl http://localhost:8080/health`

## Modulos

Cada modulo pode ser ligado/desligado independentemente via `.env`:

```
AION_ESTIXE_ENABLED=true
AION_NOMOS_ENABLED=true
AION_METIS_ENABLED=true
```

### ESTIXE — Controle e Bypass

Classifica intencoes semanticamente (embeddings, NAO pattern matching) e responde sem chamar o LLM quando possivel.

- Bypass de saudacoes, despedidas, confirmacoes
- Policy engine: bloqueio de prompt injection, PII detection
- Guardrails: filtro de output sensivel
- Intents configuraveis via YAML
- Hot-reload: `POST /v1/estixe/intents/reload`

### NOMOS — Roteamento Inteligente

Classifica complexidade do prompt e roteia para o melhor modelo.

- Heuristicas rapidas (sem ML) para score de complexidade
- Registry de modelos via YAML (multiplos providers)
- Roteamento por complexidade, custo, latencia
- Fallback chain se modelo primario falhar

### METIS — Otimizacao

Comprime prompts e otimiza respostas.

- Compressao: remove redundancias, trim de historico, dedup de system messages
- Behavior Dial: controle parametrico em tempo real
- Otimizacao pos-LLM: remove filler, ajusta densidade

## Behavior Dial

Mude o comportamento da IA sem deploy:

```bash
# Ativar modo "direto e seco"
curl -X PUT http://localhost:8080/v1/behavior \
  -H "Content-Type: application/json" \
  -d '{"objectivity": 90, "density": 80, "explanation": 80, "cost_target": "low"}'

# Verificar config atual
curl http://localhost:8080/v1/behavior

# Remover (voltar ao default)
curl -X DELETE http://localhost:8080/v1/behavior
```

## Multi-tenancy

Isole configuracoes por tenant via header:

```bash
curl -X PUT http://localhost:8080/v1/behavior \
  -H "X-Aion-Tenant: acme-corp" \
  -d '{"objectivity": 100}'
```

## API Endpoints

**LLM Proxy**

| Endpoint | Metodo | Descricao |
|----------|--------|-----------|
| `/v1/chat/completions` | POST | OpenAI-compatible proxy (Transparent mode) |
| `/v1/decide` | POST | Decision-Only: retorna block/bypass/continue sem chamar LLM |
| `/v1/chat/assisted` | POST | Assisted mode: AION decide + executa, retorna resposta + contrato |
| `/v1/decisions` | POST | Decision mode: retorna DecisionContract completo |

**Observabilidade**

| Endpoint | Metodo | Descricao |
|----------|--------|-----------|
| `/health` | GET | Status, modulos, Trust Guard |
| `/ready` | GET | Pronto para receber trafego (use no load balancer) |
| `/metrics` | GET | Prometheus scrape |
| `/version` | GET | Versao, build, estado de licenca (auth: admin/operator) |
| `/v1/stats` | GET | Metricas de decisao e economia |
| `/v1/events` | GET | Telemetria recente |
| `/v1/economics` | GET | Economia (custo real vs. default, tokens saved) |
| `/v1/intelligence/{tenant}/overview` | GET | Dashboard por tenant |

**Control Plane**

| Endpoint | Metodo | Descricao |
|----------|--------|-----------|
| `/v1/killswitch` | PUT/DELETE | Kill switch: ativa/desativa SAFE_MODE |
| `/v1/behavior` | GET/PUT/DELETE | Behavior Dial |
| `/v1/overrides` | GET/PUT/DELETE | Overrides por tenant |
| `/v1/modules/{name}` | PUT | Ligar/desligar modulo em runtime |
| `/v1/budget/{tenant}` | GET/PUT | Cap de gasto por tenant |
| `/v1/estixe/intents/reload` | POST | Recarregar intents |
| `/v1/estixe/policies/reload` | POST | Recarregar politicas |

**Dados e Auditoria**

| Endpoint | Metodo | Descricao |
|----------|--------|-----------|
| `/v1/audit` | GET | Trilha de auditoria (hash-chained) |
| `/v1/data/{tenant}` | DELETE | LGPD — apagar dados de um tenant |
| `/v1/explain/{request_id}` | GET | Explicar decisao de um request especifico |

## Fail Mode

Se o AION falhar, o request passa direto pro LLM (fail-open por default):

```
AION_FAIL_MODE=open   # default: passthrough se AION falhar
AION_FAIL_MODE=closed # bloqueia se AION falhar (compliance)
```

## Testes

```bash
pip install -e ".[dev]"
pytest tests/ -m "not slow"      # testes rapidos (~20s)
pytest tests/                    # todos (inclui testes com embedding model)
```

## Arquitetura

```
App do cliente
     |
     v
  AION (proxy local, porta 8080)
     |
     +---> ESTIXE (bypass? block?)
     |        |
     +---> NOMOS (qual modelo?)
     |        |
     +---> METIS pre (comprimir prompt)
     |        |
     +---> LLM (OpenAI/Anthropic/Google)
     |        |
     +---> METIS pos (otimizar resposta)
     |
     v
  Resposta ao cliente
     |
     v (async, Shadow Mode only — opt-in, desativado por default)
  ARGOS / Baluarte (telemetria anonima — zero dados no POC)

  ──────────────────────────────────────────────────────────
  O que SAI do ambiente do cliente (opcional, configuravel):
    • Metadados de decisao → Supabase Baluarte (nunca conteudo de mensagens)
    • Sinais de calibracao → ARGOS (Shadow Mode apenas, requer DPA)
  O que NUNCA sai: prompts, respostas, PII, dados de usuario.
  Licenca validada localmente (Ed25519, offline — sem phone-home).
```
