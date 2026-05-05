# VEREDITO DO CEIFADOR

**Projeto:** AION — Motor Realtime do Sentinela
**Repositório:** `D:\projetos\sentinela-aion-main` (branch `main`, commit `8af7d97`)
**Data:** 2026-04-30
**Modo:** `pre-launch` (read-only, time-box ~2h)
**Versão produto:** `0.1.0` (declarada em `pyproject.toml`)

---

## ⚠ ERRATA — RECALIBRAÇÃO POR MODELO DE DEPLOYMENT

Este veredito recebeu **errata formal** após o usuário/dono do produto declarar explicitamente, em duas correções consecutivas:
> 1ª: "AION fica dentro da estrutura do cliente, roda na arquitetura dele, única coisa que sai são metadados de telemetria."
>
> 2ª: "AION é agnóstico a ambiente, seja cloud ou on-prem."

Modelo confirmado: **single-tenant customer-side, ambiente-agnóstico**. Mesmo binário roda em datacenter on-prem do cliente OU em cloud do cliente (AWS/GCP/Azure/etc); sempre dentro do perímetro do cliente. "Tenant" no header é **workspace lógico interno** (squad/produto/área), não cliente-vs-cliente.

**Implicação extra de "ambiente-agnóstico":** o binário não pode contar com proteções específicas de infra (Vault, KMS, NetworkPolicy, WAF). Defaults inseguros são MAIS críticos, não menos — o ambiente não compensa.

### Erratas #2, #3 e #4 — modos POC + ambiente-agnóstico

Clarificações finais do dono:

1. AION é **agnóstico a ambiente** (on-prem do cliente OU cloud do cliente).
2. Existem **2 modelos de POC simultâneos**, ambos legítimos:
   - **POC Decision-Only**: AION só decide; cliente fala com LLM com próprias credenciais; AION não recebe credenciais. Recomendado para banco/telecom/CISO restritivo.
   - **POC Transparent**: AION decide e fala com LLM com credenciais do cliente. Integração acelerada para clientes flexíveis.

**Implicação:** os achados precisam ser lidos **por modo POC**. Veja a tabela de aplicabilidade em [errata-and-recalibration.md → Errata #4](errata-and-recalibration.md).

| Achado | Decision-Only | Transparent |
|---|:---:|:---:|
| F-15 streaming sem cap | N/A | S2 |
| F-16 per-request cost cap | N/A | **S1** |
| F-36 budget cap não-mandatório | N/A | **S1** |
| F-22 decision contract sem hashes | **S1** (contract é o produto) | S2 |
| F-37 "no LLM call" sem enforcement | **S1** | N/A |
| F-12 chat anônimo silencioso | S2 | **S1** |
| F-03/F-04/F-06/F-07/F-10/F-17/F-19 | aplicam-se em ambos | aplicam-se em ambos |

### Vereditos por modo POC (canônicos — substituem os anteriores)

> **POC Decision-Only liberada com 6 fixes obrigatórios:** F-37 (enforcement de "no LLM call"), F-03, F-04, F-06, F-07, F-10. Adicionar F-22 se prazo permite (contract com hashes).
>
> **POC Transparent liberada com 7 fixes obrigatórios:** F-16+F-36 (controle de custo), F-12 (chat anônimo), F-03, F-04, F-06, F-07, F-10.
>
> **Comum aos dois:** corrigir F-17 (702 testes) e F-19 (doc obsoleta) **antes** de qualquer apresentação cliente — credibilidade da due-diligence.

→ Detalhe completo + tabela final por modo em [errata-and-recalibration.md](errata-and-recalibration.md).

**Isso muda 4 achados (F-01, F-02, F-11, F-13)** de S1 para S2/S3 e **reforça 2 achados** (F-06, F-16) cuja gravidade é maior em on-prem do que em SaaS.

→ Detalhe completo da recalibração + decisão revisada em [errata-and-recalibration.md](errata-and-recalibration.md).
→ Placar revisado: **0 S0, 9 S1, ~22 S2, 6 S3**.
→ Decisão revisada (no fim deste documento e também em errata): **LIBERADO PARA POC SINGLE-TENANT ON-PREM com 4 fixes obrigatórios**; **NÃO LIBERADO** ainda para produção enterprise SLA sem fechar também 2 fixes adicionais.

> Os números "originais" abaixo (e em [findings.md](findings.md), [security.md](security.md) etc.) refletem a calibração **antes** desta correção. **Leia [errata-and-recalibration.md](errata-and-recalibration.md) PRIMEIRO** para a versão definitiva.

---

## 1. Escopo Declarado

- **Modo:** `pre-launch` — critério rigoroso (zero S0/S1 abertos para `LIBERADO PARA PRODUÇÃO`).
- **Time-box:** ~2h efetivos.
- **Profundidade:** blast-radius nível 2 (módulo direto + importadores diretos + contratos expostos).
- **Out-of-scope:** repo paralelo `sentinela-aion` em `D:\projetos\sentinela-aion`, memórias de sessão, `aion-console/.next/`, `node_modules/`, `__pycache__/`, `.runtime/`, benchmarks, `aion-console` em profundidade (apenas superfície).
- **Restrições de evidência:** sem rodar testes (sem env Python preparada), sem hits a serviços externos (Redis/LLM/Supabase), sem fuzzing, sem instalar dependências.
- **Promessas auditadas (15):** isolamento multi-tenant, licença Ed25519 offline, audit hash-chained HMAC, bypass zero-token (ESTIXE), bloqueio prompt injection/PII, NOMOS routing, METIS compressão, LGPD `/v1/data`, budget cap, "PII nunca sai", "702+ testes 0 falhas", performance (p95<500ms, ≥100 RPS), fail-mode configurável, kill switch global, decisão explicável `/v1/explain`.

Detalhes em [scope.md](scope.md).

---

## 2. Decisão Final

> **BLOQUEADO PARA CLIENTE ENTERPRISE MULTI-TENANT.**
> **LIBERADO PARA POC CONTROLADA SINGLE-TENANT ON-PREM** com mitigações explícitas e ADR formalizando "AION é instância única por cliente, não SaaS multi-tenant" (caso esse seja o modelo de adoção declarado).

**Justificativa em 5 linhas:**

1. RBAC concede permissão por papel mas **não amarra operator a tenant** — qualquer admin pode operar (ler insights, deletar dados LGPD) de qualquer tenant.
2. Trilha de auditoria fica forjável (SHA-256 sem HMAC) por default; license public key dev embutida sem enforcement de override; `AION_LICENSE_SKIP_VALIDATION=true` desabilita Trust Guard inteiro — três bombas de configuração que disparam silenciosamente.
3. Telemetria forwarded para ARGOS contém mensagem do usuário em texto cru, contradizendo a promessa "PII nunca sai do ambiente".
4. Métricas executivas são in-memory voláteis (zeram a cada deploy) e dependem de preços de modelo hardcoded sem fonte/timestamp; `total_spend_usd` mistura conceitos com `cost_saved` em fallback — produto diz que economiza, mas não pode provar duravelmente.
5. Documentação afirma "702+ testes" enquanto contagem direta de funções `def test_*` retorna **201**; outros artefatos (`aion/rbac.py`, `start.py`) são citados mas não existem — credibilidade da due-diligence comprometida.

---

## 3. Placar de Risco

| Severidade | Quantidade | Bloqueia? |
|------------|:----------:|:---------:|
| S0 | 0 (com configuração default) | Sim |
| S1 | **11** | Sim |
| S2 | **18** | Depende |
| S3 | **5** | Não imediato |
| S4 | 0 | Não |
| RAD ativos | 0 | Visível |
| RAD rebaixados | 9 | Sim |

> Observação: vários itens marcados como **S1** podem virar **S0** dependendo da configuração que o cliente final usar (ex: `AION_LICENSE_SKIP_VALIDATION=true` em prod, ou `AION_REQUIRE_TENANT=false` em SaaS multi-tenant). O que separa S1 de S0 aqui é a configuração de deploy — e o produto não tem um modo "production profile" que feche essas portas automaticamente.

---

## 4. Top 10 Riscos

| Rank | Severidade | Área | Problema | Por que é perigoso | Bloqueia? |
|:----:|:----------:|------|----------|--------------------|:---------:|
| 1 | S1 | Multi-tenant / RBAC | Qualquer operator com `data:delete` apaga dados de qualquer tenant; sem ownership operator↔tenant ([data_mgmt.py:25-60](aion/routers/data_mgmt.py)) | LGPD violation cross-customer; risco regulatório direto | **Sim** |
| 2 | S1 | Multi-tenant / RBAC | Qualquer operator lê insights/PII counts/savings de qualquer tenant ([intelligence.py:20-261](aion/routers/intelligence.py)) | leak de dados financeiros e operacionais entre clientes | **Sim** |
| 3 | S1 | Auditoria | `AION_SESSION_AUDIT_SECRET` opcional → audit chain SHA-256 simples, forjável ([middleware.py:362-369](aion/middleware.py)) | "tamper evidence theater" — texto literal do warning de boot; auditoria contestável | **Sim** |
| 4 | S1 | Licença | Chave pública Ed25519 dev hardcoded; sem enforcement de override em prod ([license.py:38-42](aion/license.py)) | bypass de licenciamento se cliente esquecer env | **Sim** |
| 5 | S1 | Privacidade | `event.data["input"]` carrega texto cru; vai para `/v1/events`, `/v1/explain`, ARGOS ([telemetry.py:124-142, 190-197](aion/shared/telemetry.py)) | viola promessa "PII nunca sai"; LGPD risk | **Sim** |
| 6 | S1 | Analytics executivas | `cost_saved_total` in-memory zera a cada restart ([telemetry.py:38](aion/shared/telemetry.py)) | dashboard executivo perde história em deploy; cliente vê "savings" volátil | **Sim** |
| 7 | S1 | Explainability | `/v1/explain/{request_id}` só funciona se request ainda no buffer in-memory de 1.000 ([observability.py:424-447](aion/routers/observability.py)) | auditor pede explain de 30 dias atrás → "Request not found" | **Sim** |
| 8 | S1 | Multi-tenant boundary | `AION_REQUIRE_TENANT=false` por default → bucket "default" colide múltiplos clientes ([config.py:77](aion/config.py)) | dados de clientes distintos misturados | **Sim** (se multi-tenant) |
| 9 | S1 | Auth | `AION_REQUIRE_CHAT_AUTH=true` mas sem `AION_ADMIN_KEY` → chat passa anônimo silenciosamente ([middleware.py:799-809](aion/middleware.py)) | tráfego de chat sem identidade do caller | **Sim** |
| 10 | S1 | Cost engineering | Sem per-request cost cap; streaming sem cap de output tokens ([routers/proxy.py:491-565](aion/routers/proxy.py)) | uma request gigante esgota mês inteiro / OOM em pod | **Sim** |

Outros riscos S2 importantes: `total_spend_usd` rotulagem invertida (F-08), preços hardcoded (F-09), `/health` revela license_id/expiry (F-14), behavior dial é prompt-injection (F-21), 702 testes que são 201 (F-17).

---

## 5. Mapa de Guerra Inicial

Ver [war-map.md](war-map.md). Resumo:

| Área | O que existe | Risco inicial | Precisa aprofundar? |
|---|---|---|:---:|
| Pipeline (ESTIXE/NOMOS/METIS) | sólido | streaming + behavior dial | ✓ |
| Auth + RBAC | RBAC por papel + path-tenant cross-check | falta ownership operator↔tenant | **✓** |
| Licença Ed25519 | implementação correta; bypass via env | chave dev embutida; SKIP_VALIDATION env | **✓** |
| Audit chain HMAC | implementado; forjável sem secret | secret opcional em runtime | **✓** |
| Multi-tenancy (header + path) | path_tenant cross-check | bucket "default" + ownership | **✓** |
| Telemetria | bom em counters/eventos | volátil; PII em `input` | **✓** |
| Cost engineering | budget diário/mensal ✓ | per-request gap; preços hardcoded | **✓** |
| AI/LLM Risk | bypass + policy + classifier | eval suite, output validation, versionamento | ✓ |
| Performance | circuit breaker, retries, timeouts | streaming buffer cap; latency window curta | parcial |
| Tests | 50 arquivos, ~201 funções | gaps de RBAC/PII/durabilidade; doc inflada | ✓ |
| Console (Next.js) | NextAuth v5, RBAC propagado via header | trust de header sem JWT assinado | **✓** |
| CI/CD | cosign keyless + manifest | sem pytest blocking visível | parcial |

---

## 6. Achados Detalhados

Ver [findings.md](findings.md) — 35 achados (11 S1, 18 S2, 5 S3, 1 não validado). Resumo dos 5 mais críticos abaixo.

### F-01 — RBAC sem ownership operator↔tenant

- **Severidade:** S1
- **Arquivo:** [aion/routers/data_mgmt.py:25-60](aion/routers/data_mgmt.py); [aion/middleware.py:705-754](aion/middleware.py)
- **O que está errado:** middleware checa permissão por papel (data:delete, audit:read) e cross-checa `path_tenant == header tenant`, mas não amarra a chave do operador ao tenant que ele tem direito de operar.
- **Como reproduzir:** dois tenants `acme` e `globex`; key `key_acme:operator`. Operador de `acme` envia `DELETE /v1/data/globex` com `X-Aion-Tenant: globex`. AION executa.
- **Correção obrigatória:** estender chave para `key:role:tenants_csv` ou claim no JWT do ator; rejeitar 403 quando `path_tenant ∉ tenants(caller_key)`.
- **Status:** Reprovado.

### F-03 — Audit chain forjável sem `AION_SESSION_AUDIT_SECRET`

- **Severidade:** S1
- **Arquivo:** [aion/middleware.py:362-369](aion/middleware.py)
- **O que está errado:** sem secret, `_hash_entry` faz SHA-256 simples — qualquer um com acesso ao log pode recompor entradas. Boot só warning.
- **Correção obrigatória:** introduzir `AION_PROFILE=production` que torna o secret mandatório; abort no boot se ausente.
- **Status:** Reprovado.

### F-04 — Chave pública Ed25519 dev embutida

- **Severidade:** S1
- **Arquivo:** [aion/license.py:38-42](aion/license.py)
- **O que está errado:** fallback embutido é dev/test; sem mecanismo que impeça produção sem override.
- **Correção obrigatória:** build production sem fallback; runtime exige `AION_LICENSE_PUBLIC_KEY` quando `AION_PROFILE=production`; validar fingerprint conhecido.
- **Status:** Reprovado.

### F-06 — PII em `event.data["input"]`

- **Severidade:** S1
- **Arquivo:** [aion/shared/telemetry.py:124-142, 190-197](aion/shared/telemetry.py)
- **O que está errado:** mensagem do usuário gravada bruta em event; vai para `/v1/events`, `/v1/explain`, ARGOS (se opt-in).
- **Promessa contradita:** README "O que NUNCA sai: prompts, respostas, PII, dados de usuario."
- **Correção obrigatória:** sanitizar/hashear/redactar `input` antes do `emit()`; gravar `input_hash`, `input_length`, `input_intent` em vez do texto.
- **Status:** Reprovado.

### F-07 — `cost_saved_total` volátil (MENTIRA EXECUTIVA)

- **Severidade:** S1
- **Arquivo:** [aion/shared/telemetry.py:38](aion/shared/telemetry.py)
- **O que está errado:** counter in-memory zera a cada restart. Dashboard `/v1/economics` mostra "savings_usd" baseado nesse counter.
- **Correção obrigatória:** persistir em Redis; `/v1/economics` deriva de NEMOS (já persistente) como fonte única de truth.
- **Status:** Reprovado.

Detalhe completo de F-01..F-35 em [findings.md](findings.md).

---

## 7. Riscos Aceitos Documentados (RAD)

### RAD válidos
*(zero — não há ADRs/RFCs/tickets fornecidos que satisfaçam os 6 critérios)*

| ID | Severidade | Achado | Decisão (link) | Dono | Janela | Gatilho de revisão | Status |
|----|:----------:|--------|----------------|------|--------|---------------------|:------:|
| — | — | — | — | — | — | — | — |

### RAD rebaixados (9)

| ID | Tentou ser RAD | Critério ausente | Rebaixado para |
|----|----------------|------------------|----------------|
| F-11 | "AION é single-tenant on-prem" (memória) | falta ADR formal, dono nomeado, gatilho de revisão | Bloqueio S1 (em multi-tenant) |
| F-13 | console_proxy é design intencional | falta ADR de threat model + mitigação | Bloqueio S1 |
| F-14 | `/health` exposto público é prática comum | falta doc explícito | Bloqueio S2 |
| F-21 | Behavior dial é prompt injection by design | falta ADR + alinhamento de marketing | Bloqueio S2 |
| F-24 | Pin é decisão de operação | falta política | Bloqueio S3 |
| F-15 | Streaming buffer é tradeoff conhecido | falta cap explícito + ADR | Bloqueio S2 |
| F-25 | Cache LRU local é fast path | falta ADR de roadmap distribuído | Bloqueio S2 |
| F-23 | rotate-keys é best-effort | falta runbook + dual-secret window | Bloqueio S2 |
| F-09 | Preços hardcoded é snapshot | falta ADR + processo de refresh | Bloqueio S2 |

Detalhe em [accepted-risks.md](accepted-risks.md).

---

## 8. Mentiras Encontradas

Ver [lies.md](lies.md). 16 mentiras catalogadas. Top 8:

| Tipo | Local | O que parece | O que realmente é | Risco |
|------|-------|--------------|-------------------|-------|
| DOCUMENTAÇÃO | PRODUCTION_CHECKLIST.md:109,130 | "702+ testes" | 201 funções `def test_*` (250%+ inflação) | S2 |
| EXECUTIVA | observability.py:283-291 | "cost_saved_usd" histórico | counter in-memory (zera no restart) | S1 |
| EXECUTIVA | intelligence.py:108 | "total_spend_usd" | exibe `cost_saved` quando NEMOS sem dados (rótulo invertido) | S2 |
| EXECUTIVA | models.yaml + intelligence.py:42-50 | "estimated_without_aion_usd" | preços hardcoded sem fonte/timestamp | S2 |
| FUNCIONAL | observability.py:424-447 | "Decisão explicável `/v1/explain`" | depende do buffer in-memory | S1 |
| INTEGRAÇÃO/PII | telemetry.py:124-142, 190-197 | "PII nunca sai do ambiente" | `event.data["input"]` cru forwarded a ARGOS | S1 |
| INFRAESTRUTURA | license.py:235-245 | "Licença obrigatória" | `AION_LICENSE_SKIP_VALIDATION=true` desabilita tudo | S2 |
| LICENÇA | license.py:38-42 | "Licença validada offline (Ed25519)" | chave pública dev embutida; sem enforcement de override em prod | S1 |

---

## 9. Contratos Quebrados

Ver [contracts.md](contracts.md) — 18 contratos com divergência. Resumo top 5:

| Fluxo | Cliente espera | Produtor entrega | Correção |
|-------|----------------|------------------|----------|
| `/v1/economics.cost_saved_usd` | métrica histórica durável | counter in-memory (zera no restart) | persistir em Redis/TS DB |
| `/v1/intelligence.total_spend_usd` | gasto total | exibe `cost_saved` quando histórico vazio | retornar `0.0` ou `null` |
| `/v1/explain/{request_id}` | reconstrução durável | só requests no buffer ~1.000 | persistir em store durável |
| `/v1/audit` | trilha tamper-evident HMAC | SHA-256 sem HMAC quando secret ausente | `AION_PROFILE=production` exige secret |
| `/v1/data/{tenant}` | só "dono" deleta | qualquer admin com `data:delete` deleta | RBAC ownership por tenant |

---

## 10. Fluxos Validados

Ver [flows.md](flows.md) — 23 fluxos. Resumo:

| Fluxo | Status | Falta algo? |
|-------|--------|-------------|
| F-1 chat/completions | REAL COM RISCO | streaming cap, behavior dial real, contract completo |
| F-2 /v1/decide | REAL E VALIDADO | — |
| F-3 license boot | REAL COM RISCO | SKIP_VALIDATION rejection, public key fingerprint enforcement |
| F-4 LGPD delete | PARCIAL | RBAC ownership |
| F-5 audit chain | REAL COM RISCO | secret obrigatório em prod |
| F-6 budget cap | REAL E VALIDADO | per-request cap |
| F-7 tenant isolation | REAL COM RISCO | bucket default + ownership |
| F-10 telemetry/ARGOS | PARCIAL | `input` cru |
| F-12 behavior dial | PARCIAL | promessa paramétrica vs realidade prompt injection |
| F-15 cache | REAL COM RISCO | distribuir |
| F-17 console SSO | NÃO VALIDÁVEL | JWT assinado pelo console |
| F-18 explain | FUNCIONA MAS NÃO PROVA VALOR | persistência |
| F-23 cost saving "estimated_without_aion" | MEDE MAS NÃO PROVA VALOR | preços + counters voláteis |

---

## 11. Segurança

Ver [security.md](security.md). 20 itens; 5 S1, 11 S2, 4 S3.

### AI/LLM Risks (Sub-fase 4.1)

| Tópico | Severidade |
|---|:---:|
| Prompt injection direto/indireto | S2 |
| System prompt leakage | S2 |
| Output validation pós-LLM (METIS post optimizer scope) | S2 |
| Hallucination boundaries | S3 |
| Eval suite adversarial estruturada | S2 |
| Model fallback | ✅ ok |
| Token budget runaway / per-request cap | **S1** |
| PII em prompts/telemetria | **S1** |
| Capability escape | ✅ ok |
| Prompt + modelo + tools versioning | S2 |
| RAG-specific | N/A |

---

## 12. Testes Ausentes ou Fracos

Ver [tests.md](tests.md). Gaps críticos:

| Área | Problema | Teste necessário | Prioridade |
|------|----------|-------------------|:----------:|
| RBAC ownership cross-tenant | sem teste | operator A tenta DELETE /v1/data/B → 403 | **S1** |
| License skip rejection em prod | sem teste | `AION_PROFILE=production` + `SKIP_VALIDATION=true` → exit 1 | **S1** |
| `event.data.input` sanitizado | sem teste | mensagem com PII → assert que `input` não contém texto cru | **S1** |
| `cost_saved` durável | sem teste | restart → counter mantido | S1 |
| `/v1/explain` durável | sem teste | 1.500 events emitted → 1º ainda findable | S1 |
| Console SSO trust | sem teste | chave console_proxy + role admin sem SSO upstream → 401 | S1 |
| Per-request cap | sem teste | request grande → 402 | S2 |
| Streaming OOM | sem teste | mock 1M tokens → abort estruturado | S2 |
| Eval suite adversarial | parcial | 50+ casos com baseline FP/TP, CI quebra se regredir | S2 |
| `_TENANT_PATTERN` segurança | sem teste | payloads `..`, NULL, unicode | S2 |

---

## 13. God Files e Crimes de Manutenção

Ver [god-files.md](god-files.md).

| Arquivo | Crime | Consequência | Ação |
|---------|-------|--------------|------|
| [aion/middleware.py](aion/middleware.py) (~36 KB / 850+ linhas) | RBAC + audit + rate limit + tenant + chain — toda constituição em um arquivo | mudanças em RBAC arriscam quebrar audit | quebrar em `aion/security/`, `aion/audit/` |
| [aion/pipeline.py](aion/pipeline.py) (~22 KB) | orchestrator + cache lookup + telemetria | tests acoplados | extrair `aion/pipeline/` package |
| [aion/proxy.py](aion/proxy.py) | client + circuit breaker + retry + format conversion | adicionar provider arriscado | extrair `aion/proxy/clients/` |
| [aion/routers/observability.py](aion/routers/observability.py) | health + metrics + stats + events + economics + ... | mudança em economia mexe em health | dividir |

---

## 14. Performance, Escala, Resiliência

Ver [performance.md](performance.md). Resumo:

| Ponto | Risco | Severidade | Correção |
|---|---|:---:|---|
| Streaming buffer-accumulate-flush sem cap | OOM em 1M tokens | S2 | hard cap |
| Rate limit fallback in-memory | bypass via round-robin | S2 | exigir Redis em prod |
| Cache LRU per-replica | hit rate degrada multi-replica | S2 | distribuir |
| `_event_buffer` deque maxlen=10.000 | perda em alto volume | S1 | drain async |
| Counters in-memory | métricas voláteis | S1 | persistir |

### Cost Engineering

| Vetor | Existe guard? | Risco | Severidade |
|-------|:-------------:|-------|:----------:|
| Hard cap diário/mensal por tenant | ✅ | — | — |
| Hard cap por request | ❌ | request grande esgota mês | **S1** |
| Cap em tokens output (streaming) | ❌ | output ilimitado | **S1** |
| Custo por unidade de valor | parcial | volátil | S1 |
| LLM token cost (preços corretos) | parcial | hardcoded sem fonte/timestamp | S2 |
| Cache hit rate medido | ✅ | — | — |
| Alertas com dono nomeado | ❌ | sem ownership | S2 |

---

## 15. Observabilidade e Prova

Ver [observability.md](observability.md).

| Evento crítico | Existe log? | Existe rastreio? | Existe evidência? | Gap |
|---|:---:|:---:|:---:|---|
| Decisão BYPASS/BLOCK | ✅ | ✅ | parcial | explain durability |
| Audit chain entry | ✅ | ✅ | ⚠ HMAC opcional | secret obrigatório |
| PII intercepted | ✅ counts | ✅ | ⚠ input cru ainda guardado | sanitização |
| Block reason | ✅ | parcial | ⚠ buffer in-memory | persistir |
| License state | ✅ | ✅ | — | — |
| Latency p95/p99 | ✅ | parcial | janela curta (deque 1000) | Prometheus histogram |
| `tenant=` label em métricas | ❌ | ❌ | ❌ | adicionar |

> "Sem audit chain assinado, sem `/v1/explain` durável e sem métricas executivas persistentes, o produto **funciona em demo, falha em compliance**."

---

## 16. Auditoria de Analytics e Valor de Negócio

Ver [analytics.md](analytics.md).

### Eventos Críticos Ausentes

- `tenant_ownership_violation_attempt`
- `audit_secret_rotated` / `chain_break`
- `first_value_for_tenant` (TTFV)
- `policy_version_applied` (rastreabilidade)
- `audit_export_requested` (compliance)

### Métricas de Produto Ausentes

- TTFV, DAU, tenants ativos, profundidade de uso, frequência por tenant.

### Métricas de Negócio Ausentes (vs promessas)

- Isolamento tenant: sem métrica de tentativa de violação.
- Compressão METIS: sem `compression_ratio` exposto.
- Multi-cliente: sem agregado fleet-wide.
- ROI: fórmula simples, insumos não rastreáveis.

### Funis Cegos

- Ativação (cliente liga AION → primeiro valor): sem instrumentação.
- Adoção módulos: sem segmentação.

### Dashboards Cegos

- `/v1/intelligence/{tenant}/overview` responde "o que aconteceu" parcialmente; **não responde "o que devo fazer agora"**, **sem evidência rastreável**, **sem custo da inação**.

### Veredito Analítico

> **PARCIALMENTE MENSURÁVEL** com forte tendência a **CEGO PARA VALOR**.
>
> Forte em instrumentação técnica (counters Prometheus, audit chain, NEMOS, eventos com correlation_id). Fraco em durabilidade dos dados executivos, baseline de preços com fonte rastreável, funil de ativação, comparações antes/depois, segmentação fleet-wide.
>
> Promessas de economia são apresentadas em telas executivas, mas usam preços que podem estar defasados, resetam a cada restart, misturam conceitos opostos em fallback, e não têm baseline pré-AION para comparação real.

> "Sem analytics confiável, o produto pode até funcionar, mas não consegue provar que importa."

---

## 17. Plano de Execução para Sair do Inferno

Ver [execution-plan.md](execution-plan.md). Resumo:

### Agora ou nada (bloqueia cliente)

| Item | Severidade | Esforço |
|------|:----------:|:-------:|
| RBAC ownership operator↔tenant | S1 | L |
| `AION_PROFILE=production` (modo seguro by default) | S1 | M |
| Sanitização de PII em `event.data["input"]` | S1 | S |
| Persistir métricas executivas duráveis | S1 | M |
| `total_spend_usd` retornar `null` quando vazio | S2 | S |
| `/v1/explain` durável em Redis/Supabase | S1 | M |
| Per-request cost cap + max_output_tokens cap | S1/S2 | M |
| `audit_secret_rotated` event + dual-secret window | S2 | M |
| Validar `X-Aion-Actor-Role` via JWT do console | S1 | L |

### Antes da POC

Schema YAML preço com `pricing_observed_at`, `/health` minimal, telemetry schema bump (`environment`, `feature_version`), lockfile uv/pip-tools, doc cleanup (rbac.py, start.py, 702 testes), legacy admin keys rejeitadas, cache distribuído, regex tenant revisado, sanitização Actor-Reason, eval suite adversarial, seed_sandbox gate.

### Antes de produção

Behavior dial paramétrico real ou reposicionamento, decision_contract com hashes, Prometheus tenant label, latency histogram, `_TRUSTED_PROXY_ROLES` documentado, `hmac.compare_digest`, god-files breakdown (XL), OpenAPI compartilhado FE↔BE, pip-audit weekly CI.

**Estimativa total:** 14–24 dev-weeks (2 devs sêniores).

---

## 18. Checklist Final

Ver [checklist.md](checklist.md). Resumo:

```
[x]  10 itens                                        — escopo, tipo, secrets, logs, deploy, eventos críticos, etc.
[?]   8 itens                                        — não validados (testes, build, AI/LLM mitigations parciais)
[~]   2 itens                                        — parcial (métricas de produto, funis)
[ ]  19 itens                                        — quebrados/faltando (incluindo isolamento, auth, audit, cost, dashboards)
```

---

## Frase de Encerramento

> **POC permitida, mas sob contenção.** Há riscos conhecidos que precisam ser explicitados ao cliente — em particular: o produto **não amarra operadores aos seus tenants**, a **trilha de auditoria fica forjável** com configuração default, **prompts do usuário podem sair do ambiente** via telemetria opt-in, e **métricas de economia são voláteis** (zeram a cada deploy). Antes de venda enterprise multi-tenant, fechar o Bloco 1 do plano de execução.

> **Funciona, mas está cego.** Sem analytics confiável, não prova valor.

---

## Arquivos de evidência

- [scope.md](scope.md) — escopo, time-box, restrições, promessas
- [war-map.md](war-map.md) — Fase 0
- [lies.md](lies.md) — Fase 1 (16 mentiras)
- [contracts.md](contracts.md) — Fase 2 (18 contratos)
- [flows.md](flows.md) — Fase 3 (23 fluxos)
- [security.md](security.md) — Fase 4 + sub-bloco AI/LLM (20 riscos)
- [tests.md](tests.md) — Fase 5
- [god-files.md](god-files.md) — Fase 6
- [performance.md](performance.md) — Fase 7 + sub-bloco Cost Engineering
- [observability.md](observability.md) — Fase 8
- [analytics.md](analytics.md) — Fase 9
- [findings.md](findings.md) — 35 achados consolidados
- [accepted-risks.md](accepted-risks.md) — RAD válidos (0) + rebaixados (9)
- [recommended-fixes.md](recommended-fixes.md) — 6 prompts de correção
- [execution-plan.md](execution-plan.md) — 3 blocos
- [checklist.md](checklist.md) — checklist final
