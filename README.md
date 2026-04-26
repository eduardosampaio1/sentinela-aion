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

Dois modos de operacao, escolha o que se encaixa no cliente:

**Modo Decision** — AION decide, sua app chama o LLM (sem compartilhar chaves):
```bash
curl -O https://raw.githubusercontent.com/eduardosampaio1/sentinela-aion/main/docker-compose.decision.yml
echo "AION_LICENSE=<seu-jwt>" > .env
docker compose -f docker-compose.decision.yml up -d
```

**Modo Proxy** — AION intercepta tudo, incluindo a chamada ao LLM (zero-code na app):
```bash
# .env com AION_LICENSE + chave do LLM (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
docker compose -f docker-compose.proxy.yml up -d
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

| Endpoint | Metodo | Descricao |
|----------|--------|-----------|
| `/v1/chat/completions` | POST | OpenAI-compatible proxy |
| `/health` | GET | Status e modulos ativos |
| `/v1/stats` | GET | Metricas de decisao e economia |
| `/v1/events` | GET | Telemetria recente |
| `/v1/models` | GET | Modelos disponiveis |
| `/v1/behavior` | GET/PUT/DELETE | Behavior Dial |
| `/v1/estixe/intents/reload` | POST | Recarregar intents |
| `/v1/estixe/policies/reload` | POST | Recarregar politicas |

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
```
