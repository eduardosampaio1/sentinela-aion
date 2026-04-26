# AION — Arquitetura e Modelo de Implantação

## Visão Geral

O AION é um proxy gateway que roda **dentro do ambiente do cliente**. Em produção
real, o AION nunca é um serviço gerenciado na nuvem da Baluarte — ele roda no
ambiente do cliente, usando os recursos de infraestrutura do cliente.

```
┌─────────────────────────────────────────────────┐
│                 Ambiente do cliente               │
│                                                   │
│   App do cliente                                  │
│        │                                          │
│        ▼                                          │
│   AION (proxy local)                              │
│        │                                          │
│        ├──▶ ESTIXE  (bypass/block)                │
│        │                                          │
│        ├──▶ NOMOS   (roteamento, modelo)          │
│        │                                          │
│        ├──▶ METIS   (compressão de contexto)      │
│        │                                          │
│        ▼                                          │
│   LLM provider (OpenAI / Anthropic / etc.)        │
│        │                                          │
│        ▼                                          │
│   Resposta ao cliente                             │
│                                                   │
│   Redis do cliente ◀──── lifecycle Collective     │
│                          (apenas status admin)    │
└─────────────────────────────────────────────────┘
         │
         │  async, Shadow Mode only
         │  opt-in, desativado por default
         ▼
┌────────────────────────┐
│  Baluarte (AION cloud) │
│  ARGOS telemetria      │
│  (sem PII, sem prompts)│
└────────────────────────┘
```

---

## Três Fases de Implantação

### Fase 1 — POC (padrão)

| Característica | Valor |
|---------------|-------|
| Onde roda | Ambiente do cliente (Docker/bare-metal) |
| Redis | Redis do próprio cliente |
| Telemetria externa | **Zero** — nada sai do ambiente |
| Dependência de internet | Apenas para chamar o LLM provider |
| Baluarte cloud | Não utilizada |
| Supabase Baluarte | Não utilizada |
| DPA necessário | Não |
| `ARGOS_TELEMETRY_URL` | Não configurado |
| `AION_CONTRIBUTE_GLOBAL_LEARNING` | `false` (default) |

**Tudo que o AION processa — prompts, respostas, logs, Redis — fica 100% no
ambiente do cliente.**

---

### Fase 2 — Shadow Mode (opt-in, fase futura)

Ativado apenas após:
1. Cliente solicita explicitamente
2. DPA (Data Processing Agreement) assinado
3. Configuração deliberada das variáveis de ambiente abaixo

| Configuração | Valor |
|-------------|-------|
| `ARGOS_TELEMETRY_URL` | URL do endpoint Baluarte |
| `AION_CONTRIBUTE_GLOBAL_LEARNING` | `true` |

**O que é enviado ao Baluarte em Shadow Mode:**
- Sinais agregados de calibração (contagens, médias de confiança)
- Sem conteúdo de usuário
- Sem prompts
- Sem PII

**O que NUNCA é enviado:**
- Conteúdo de mensagens
- Respostas do LLM
- Dados de usuários
- Chaves de API

---

### Fase 3 — AION Collective (fase futura)

Permite que o Baluarte envie policies atualizadas para o cliente:
- Policies assinadas digitalmente pelo Baluarte
- Instalação manual no pipeline do cliente
- Baluarte **nunca** acessa o Redis do cliente
- Baluarte **nunca** lê dados do pipeline em tempo real

---

## AION Collective — Phase 0 (implementação atual)

O Collective Phase 0 é **exclusivamente** um catálogo editorial com rastreamento
administrativo de ciclo de vida.

### O que está implementado

```
GET  /v1/collective/policies          → lê collective_policies.yaml (bundled)
GET  /v1/collective/policies/{id}     → detalhe com provenance
GET  /v1/collective/installed/{tenant} → lista de installs (lê Redis do cliente)
POST /v1/collective/policies/{id}/install → registra status "sandbox" no Redis
PUT  /v1/collective/policies/{id}/promote → atualiza status no Redis
```

### O que o Collective Phase 0 NÃO faz

| Afirmação incorreta | Realidade |
|--------------------|-----------|
| "Policy instalada aplica regras no pipeline" | Falso — status é apenas administrativo |
| "Shadow Mode executa avaliação paralela" | Falso — é só uma label de status |
| "Feed cross-tenant está ativo" | Falso — Shadow Mode roadmap, sem dados reais |
| "ARGOS agrega sinais de múltiplos clientes" | Falso em POC — zero telemetria externa |

### Onde o status de install é armazenado

```
Redis do cliente:
aion:collective:{tenant}:installs:{policy_id}
→ {policy_id, tenant, status, installed_at, version}
```

O AION Baluarte **não acessa este Redis**. Nenhum dado de install é enviado
ao Baluarte em Phase 0.

### Lifecycle de status (administrativo)

```
[não instalado] → sandbox → shadow → production
                               ↑
                    Apenas label — sem efeito no pipeline
```

---

## Módulos do Pipeline

### ESTIXE — Controle e Bypass

- Classifica a intenção do prompt por embeddings
- Responde sem LLM se intenção é trivial (bypass)
- Bloqueia prompts que violam policies configuradas em `config/policies.yaml`
- **NÃO lê** keys `aion:collective:*` do Redis em nenhuma circunstância

### NOMOS — Roteamento Inteligente

- Escolhe o melhor modelo para o prompt (custo × latência × capacidade)
- Configurado via `config/models.yaml`
- **NÃO lê** keys `aion:collective:*` do Redis

### METIS — Otimização de Contexto

- Comprime histórico de conversa para reduzir tokens
- Aplica Behavior Dial para ajustar estilo de resposta
- **NÃO lê** keys `aion:collective:*` do Redis

---

## Variáveis de Ambiente — Referência Rápida

| Variável | Default | Quando usar |
|----------|---------|------------|
| `AION_ADMIN_KEY` | `""` | Sempre — autenticação da console |
| `REDIS_URL` | `None` | Recomendado — Redis do cliente |
| `ARGOS_TELEMETRY_URL` | `None` | **Apenas Shadow Mode** — nunca no POC |
| `AION_CONTRIBUTE_GLOBAL_LEARNING` | `false` | **Apenas Shadow Mode** |
| `AION_COLLECTIVE_ENABLED` | `true` | Mantido — catálogo editorial |
| `AION_WORKERS` | `1` | Produção multi-core |
| `PORT` | `8080` | Render/Railway/Heroku |

---

## Redis — Separação de Contextos

| Redis | Dono | Usado para |
|-------|------|-----------|
| Redis do cliente | Cliente | AION em produção real — lifecycle Collective, NEMOS, velocity |
| Redis Baluarte (Upstash) | Baluarte | Demo/Render da Baluarte, POC interno, desenvolvimento |

**Em implantação real no cliente:** o `REDIS_URL` aponta para o Redis do cliente.
O Baluarte nunca tem acesso a este Redis.

---

## Decisão de Arquitetura — Por que sem cloud no POC

A separação POC-local ↔ Shadow-Mode-opt-in existe por design:

1. **Compliance**: Prompts podem conter PII. Zero telemetria = zero risco LGPD/GDPR no POC.
2. **Confiança**: O cliente pode auditar que nada sai (Wireshark, firewall egress).
3. **Velocidade de sales**: Sem DPA, sem procurement, sem security review — instala e roda.
4. **Fallback garantido**: AION funciona 100% sem internet (exceto para o LLM).
