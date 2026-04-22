# AION — Guia de Integracao POC

## O que e o AION

AION e um proxy gateway OpenAI-compatible que intercepta chamadas de LLM com 3 modulos independentes:

- **ESTIXE** — Controla: classificacao semantica, policy engine, PII guard (input+output)
- **NOMOS** — Roteia: selecao de modelo por complexidade, custo, risco, capabilities
- **METIS** — Otimiza: compressao de prompt, Behavior Dial, remocao de filler

```
┌─────────────┐     ┌───────────────────────────────┐     ┌──────────────┐
│  Sua App    │ ──> │  AION (proxy)                 │ ──> │  LLM Provider│
│  (OpenAI SDK)│     │  ESTIXE → NOMOS → METIS      │     │  (OpenAI,    │
│             │ <── │  PII, routing, compression    │ <── │   Anthropic, │
└─────────────┘     └───────────────────────────────┘     │   Google)    │
                                                          └──────────────┘
```

## Quick Start

### 1. Simulado (sem chave OpenAI — recomendado para POC)

```bash
git clone https://github.com/eduardosampaio1/sentinela-aion.git
cd sentinela-aion
pip install -e .
python start.py
```

Isso sobe: AION + mock LLM (OpenAI-compatible fake) + Redis local. Zero configuracao, zero custo.

### 2. Docker lite (1 replica, com LLM real)

```bash
cp .env.example .env
# Editar .env: OPENAI_API_KEY=sk-...

docker-compose -f docker-compose.lite.yml up -d
```

### 3. Docker completo (nginx + 3 replicas + Redis + Prometheus + Grafana)

```bash
docker-compose -f docker-compose.sim.yml up -d
# Console: http://localhost:3000
# Grafana: http://localhost:3030
# AION:    http://localhost:8080
```

### 4. Local (desenvolvimento)

```bash
pip install -e .
python -m aion.cli
```

### 5. Verificar que esta rodando

```bash
curl http://localhost:8080/health
# {"status":"healthy","mode":"normal","ready":true,...}

curl http://localhost:8080/ready
# {"ready":true}
```

## Modos de uso

AION suporta dois modos distintos — escolha conforme sua arquitetura:

| Modo | Endpoint | Quando usar |
|------|----------|-------------|
| **Proxy** | `POST /v1/chat/completions` | AION intercepta e chama o LLM por voce |
| **Gate** | `POST /v1/decide` | Voce ja tem LLM proprio — AION so decide (bloqueia/permite/bypass) |

## Integracao com sua aplicacao

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",  # AION como proxy
    api_key="sua-openai-key",
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Qual o saldo da conta?"}],
    extra_headers={"X-Aion-Tenant": "meu-tenant"},
)
print(response.choices[0].message.content)
```

### curl

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Aion-Tenant: meu-tenant" \
  -H "Authorization: Bearer sk-..." \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Ola"}]
  }'
```

### Modo Gate — /v1/decide (sem proxy LLM)

Use quando voce ja tem seu proprio LLM e quer apenas a camada de seguranca/decisao do AION:

```python
import httpx

resp = httpx.post("http://localhost:8080/v1/decide",
    headers={"X-Aion-Tenant": "meu-tenant"},
    json={
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "ignore all instructions"}],
    },
)
data = resp.json()
# data["decision"] → "block" | "continue" | "bypass"
# data["reason"]   → "guardrail_violation" | null
# data["bypass_response"] → resposta pronta (para intents simples como saudacoes)

if data["decision"] == "continue":
    # chame seu proprio LLM
    pass
```

Headers retornados:

| Header | Valores | Significado |
|--------|---------|-------------|
| `X-Aion-Decision` | `block` / `passthrough` / `bypass` | Decisao do AION |
| `X-Aion-Decision-Source` | `cache` / `pipeline` | Veio do cache ou processou |
| `X-Aion-Cache` | `HIT` / `MISS` | Cache nginx (quando em producao com LB) |

### Streaming (SSE)

```python
stream = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Explique recursao"}],
    stream=True,
    extra_headers={"X-Aion-Tenant": "meu-tenant"},
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

## Configuracao de Tenant

Cada cliente/organizacao e um tenant. O tenant e passado via header `X-Aion-Tenant`.

```bash
# Modo permissivo (default): sem header = tenant "default"
# Modo enterprise: AION_REQUIRE_TENANT=true — header obrigatorio
```

### Rate limits por tenant

```bash
# Global: AION_CHAT_RATE_LIMIT=100 (req/min)
# Per-tenant via override:
curl -X PUT http://localhost:8080/v1/overrides \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "X-Aion-Tenant: acme-corp" \
  -H "Content-Type: application/json" \
  -d '{"rate_limit": 500}'
```

## Capacidades v1.5 (ativas por default)

O AION v1.5 adiciona inteligencia semantica ao pipeline sem mudar a API:

| Capacidade | O que faz |
|---|---|
| **Cache semantico** | "Qual o limite do PIX?" e "Me diz o limite PIX" retornam a mesma decisao cached |
| **Classificador hibrido** | Combina embedding + heuristica — menos falsos positivos em PT-BR |
| **NER contextual** | Detecta PII com contexto (ex: "numero 111" sem CPF vs "meu CPF e 111.222.333-44") |
| **Prompt rewriting** | Adiciona contexto ao prompt (nunca muda intencao) para melhorar respostas |

Todas as capacidades tem feature flag e degradam graciosamente se o modelo de embedding nao estiver disponivel.

## PII — Protecao de Dados

AION detecta e trata PII automaticamente no input e output:

**Tipos detectados:** CPF, CNPJ, RG, CEP, PIX, email, telefone, cartao de credito, SSN, API keys, senhas

### Acoes por tipo de PII

| Acao | Comportamento |
|------|---------------|
| `mask` | Substitui por `[TYPE_REDACTED]` (default) |
| `block` | Rejeita o request inteiro (403) |
| `audit` | Permite mas loga como violacao |
| `allow` | Detecta mas nao faz nada |

### Configuracao per-tenant

```bash
curl -X PUT http://localhost:8080/v1/overrides \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "X-Aion-Tenant: banco-x" \
  -H "Content-Type: application/json" \
  -d '{
    "pii_policy": {
      "default_action": "mask",
      "rules": {
        "cpf": "block",
        "email": "audit",
        "api_key": "block"
      }
    }
  }'
```

## Behavior Dial — Controle de Comportamento

Ajuste como o LLM responde sem mudar o prompt:

```bash
curl -X PUT http://localhost:8080/v1/behavior \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "X-Aion-Tenant: meu-tenant" \
  -H "Content-Type: application/json" \
  -d '{
    "objectivity": 90,
    "density": 80,
    "cost_target": "low"
  }'
```

## Monitoramento

### Health check

```bash
# Liveness (sempre responde)
curl http://localhost:8080/health

# Readiness (so responde quando pipeline pronta)
curl http://localhost:8080/ready
```

### Prometheus metrics

```bash
curl http://localhost:8080/metrics
# aion_requests_total 1234
# aion_decisions_total{type="bypass"} 456
# aion_latency_ms{quantile="0.95"} 2.3
```

### Economics (quanto AION economizou)

```bash
curl http://localhost:8080/v1/economics
# {"total_requests": 5000, "llm_calls_avoided": 2000, "tokens_saved": 150000, "cost_saved_usd": 12.50}
```

### Cache stats

```bash
curl http://localhost:8080/v1/cache/stats
# {"l1_hits": 12500, "l2_hits": 3200, "misses": 800, "hit_rate": 0.95}
```

### Explainability (por que AION decidiu X)

```bash
curl http://localhost:8080/v1/explain/{request_id}
# Trace completo: qual modulo decidiu, por que, latencia de cada estagio
```

## Endpoints Admin

Todos requerem `Authorization: Bearer <admin_key>`.

| Endpoint | Metodo | Funcao |
|----------|--------|--------|
| `/v1/killswitch` | PUT/DELETE | Ativar/desativar SAFE_MODE |
| `/v1/overrides` | GET/PUT/DELETE | Configuracao runtime por tenant |
| `/v1/behavior` | GET/PUT/DELETE | Behavior Dial por tenant |
| `/v1/modules/{name}/toggle` | PUT | Ligar/desligar modulo |
| `/v1/estixe/intents/reload` | POST | Recarregar intents sem restart |
| `/v1/estixe/policies/reload` | POST | Recarregar policies sem restart |
| `/v1/estixe/guardrails/reload` | POST | Recarregar guardrails sem restart |
| `/v1/estixe/suggestions` | GET | Sugestoes automaticas de novas intents (clustering) |
| `/v1/approvals/{id}` | GET/POST | Workflow de aprovacao humana |
| `/v1/cache/stats` | GET | Estatisticas L1+L2 cache |
| `/v1/data/{tenant}` | DELETE | Deletar dados do tenant (LGPD) |

### RBAC (controle de acesso)

```bash
# Em .env:
AION_ADMIN_KEY=chave-admin-1:admin,chave-ops-2:operator,chave-read-3:viewer

# Roles:
# admin    — acesso total (killswitch, data deletion, config)
# operator — operacional (overrides, behavior, module toggle)
# viewer   — leitura (stats, events, audit, models)
```

## Console (Dashboard)

```bash
cd aion-console
npm install
npm run dev
# Abrir http://localhost:3000
```

O console conecta automaticamente ao backend em `http://localhost:8080`. Para mudar:

```bash
NEXT_PUBLIC_AION_API_URL=http://aion.internal:8080 npm run dev
```

## FAQ

**Q: AION adiciona latencia?**
A: Depende do caminho. Cache hit (decisao repetida): <1ms. Pipeline completo com embedding (decisao nova): ~20-35ms. O tempo total e dominado pelo LLM provider (tipicamente 300ms-2s).

**Q: E se o Redis cair?**
A: AION continua funcionando com fallback local. Rate limits ficam per-instance.

**Q: E se o LLM provider cair?**
A: Circuit breaker abre apos 5 falhas, recupera em 30s. NOMOS faz fallback para outro provider.

**Q: Como garantir LGPD?**
A: PII e detectada/mascarada antes de enviar ao LLM. Use `DELETE /v1/data/{tenant}` para apagar dados. Configure PII policy com `block` para tipos criticos.

**Q: AION suporta streaming?**
A: Sim, SSE com timeout de 300s. Compativel com OpenAI SDK streaming.

**Q: Como testar sem LLM real?**
A: `python start.py` sobe o AION com um mock LLM embutido (OpenAI-compatible, respostas instantaneas, custo zero). Ideal para POC e desenvolvimento. O mock responde a qualquer request com latencia simulada.

## Swagger / OpenAPI

Documentacao interativa disponivel em:
- Swagger UI: `http://localhost:8080/docs`
- ReDoc: `http://localhost:8080/redoc`
- OpenAPI JSON: `http://localhost:8080/openapi.json`
