# Errata + Recalibração

**Data:** 2026-04-30 (após auditoria inicial)

## Contexto da errata

Erro de calibração do auditor: tratei a auditoria como se AION fosse **SaaS multi-tenant compartilhado** (modelo "tenants são clientes distintos"). O modelo real, declarado pelo dono do produto em duas correções consecutivas e já registrado em memória `feedback_aion_deployment_model.md`:

> 1ª correção: "AION fica dentro da estrutura do cliente, roda na arquitetura dele, única coisa que sai são metadados de telemetria."
>
> 2ª correção (clarificação): "AION é agnóstico a ambiente, seja cloud ou on-prem."

Modelo consolidado: **single-tenant customer-side, ambiente-agnóstico**. Mesmo binário roda em datacenter on-prem do cliente OU em cloud do cliente (AWS/GCP/Azure/etc). Sempre dentro do perímetro do cliente.

Implicação:
- AION é **deployado por cliente, dentro do perímetro do cliente** (qualquer infra).
- "Tenant" no código (header `X-Aion-Tenant`) é **workspace lógico interno** (squad / produto / área), **não cliente-vs-cliente**.
- A "única coisa que sai" do perímetro do cliente é telemetria de metadados (Supabase central com `decision`, categoria de intent/risk, tokens, cost, contadores — sem prompt/response cru).
- Cliente controla a infra; concedeu a si mesmo o admin; a auditoria deve assumir o **threat model interno** ao perímetro do cliente, não cross-customer.

### Implicação extra de "ambiente-agnóstico"

Como o mesmo binário precisa funcionar em infraestruturas variadas (k8s on-prem, ECS, GKE, AKS, Cloud Run, VM single-node, etc.), o produto **não pode assumir nenhuma proteção específica de infra** (Vault, KMS, IAM da cloud, security group, WAF, etc.). Tudo que precisa virar garantia de segurança tem que vir do **binário** — o que **reforça** (não atenua) a urgência dos fixes:

- **F-03** (audit secret obrigatório por `AION_PROFILE=production`) — não dá para confiar que "Vault/Secrets Manager está na frente injetando o segredo".
- **F-04** (chave pública dev embutida) — não dá para confiar que "build pipeline da cloud do cliente injeta a chave certa".
- **F-12** (chat anônimo se admin_key vazia) — não dá para confiar que "VPC / security group / NetworkPolicy bloqueia tráfego externo".
- **F-36** (budget cap não-mandatório) — não dá para confiar que "o time de FinOps do cliente tem alerta no Cost Explorer / Cost Management".

**Defaults inseguros são MAIS críticos em produto ambiente-agnóstico**, porque o ambiente não compensa.

---

## Errata #2 — Modo POC Decision-Only é o caminho crítico (não Transparent)

3ª clarificação do dono do produto:
> "AION o cliente tem a opção de falar ou não com o LLM. Na POC já é decidido que ela só decide e avisa o cliente que envia para o LLM."

Confirmado em [docker-compose.poc-decision.yml:1-38](docker-compose.poc-decision.yml) e em [docs/poc-integration-guide.md](docs/poc-integration-guide.md):

> "POC Decision-Only — recomendado para banco, telecom e enterprise restritivo. AION decide (bloqueia / bypass / aprova). Sua app chama o LLM com suas próprias credenciais. **AION não recebe credencial de LLM.**"

**Endpoint principal em POC:** `POST /v1/decide` (retorna `{decision, bypass_response, metadata}` sem chamar LLM).
**Endpoint NÃO usado em POC:** `POST /v1/chat/completions` (proxy transparente).

### Achados que mudam de aplicabilidade

| ID | Severidade revisada (pós-errata #1) | Aplicabilidade revisada (errata #2) | Novo status |
|---|:---:|---|:---:|
| **F-15** Streaming buffer sem cap | S2 | só em Transparent mode (AION chama LLM); em POC Decision-Only **não há streaming** | **N/A em POC** / S2 em Transparent |
| **F-16** Per-request cost cap ausente | S1 | em POC Decision-Only, AION não paga (cliente paga); o cap deveria ser advisory; em Transparent é S1 | **N/A em POC** / S1 em Transparent |
| **F-36** Budget cap não-mandatório | S1 | mesma lógica — AION não paga em POC; cliente vê fatura direta na sua conta OpenAI | **N/A em POC** / S1 em Transparent |
| **F-09** Preços hardcoded | S2 | em POC, métrica é "cost_saved advisory"; em Transparent vira billing-of-record | **S2 em ambos** (precisa fonte rastreável de qualquer forma para o dashboard ser confiável) |
| **F-22** Decision contract sem modified_request | S2 | em POC Decision-Only, **o contract é o produto principal** — agrava o gap | **S1 em POC** (contract é a interface), S2 em Transparent |

### Achado novo: F-37 — Promessa "AION não chama LLM em POC" sem enforcement técnico

- **Severidade:** **S1** (em POC para banco/telecom/CISO restritivo)
- **Área:** Promessa de produto / Compliance enterprise
- **Arquivos:**
  - [aion/config.py:111-117](aion/config.py) — `mode` é informacional: `# Não altera o comportamento do pipeline (os módulos é que controlam o comportamento).`
  - [aion/routers/observability.py:136-143](aion/routers/observability.py) — `executes_llm` é só um boolean exposto no `/health` (deriva de `nomos_enabled` + `default_provider` + `mode`); **não é um guard de runtime**.
  - [aion/routers/proxy.py](aion/routers/proxy.py) — `/v1/chat/completions` (Transparent) **roda no mesmo binário, sem validar `AION_MODE`**.
  - [docker-compose.poc-decision.yml:42-80](docker-compose.poc-decision.yml) — não inclui `OPENAI_API_KEY` etc., mas isso é **convenção do compose**, não enforcement no código.
- **O que está errado:** a promessa-chave para banco/telecom é "AION nunca chama o LLM, AION nunca recebe credenciais de LLM". Mas o produto **não tem kill switch técnico** que garanta isso:
  1. Se um operator do cliente, por engano, definir `OPENAI_API_KEY=...` no `.env` (ex: copiou do `.env.example` sem comentar);
  2. Se uma aplicação interna do cliente, por engano, chamar `POST /v1/chat/completions` em vez de `POST /v1/decide`;
  3. Se o `aion-console` ou outro consumidor interno disparar uma rota Transparent;
  → **AION chama o LLM normalmente**. A promessa de "AION nunca recebe credencial de LLM" depende de **disciplina operacional do cliente**, não de design.
- **Impacto real:** CISO de banco aprova POC com base na arquitetura "AION é caixa de decisão isolada"; se um incidente revelar que `/v1/chat/completions` estava ativo no mesmo container, o aprovação é revertida e o vendor fica queimado.
- **Correção obrigatória:**
  1. Quando `AION_MODE=poc_decision` ou `AION_MODE=decision_only`, **rejeitar com 403** em `/v1/chat/completions`, `/v1/chat/assisted` e qualquer rota que invoque `forward_request`.
  2. Boot abortar (sys.exit) se `AION_MODE in (poc_decision, decision_only)` E qualquer credencial de LLM (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AION_DEFAULT_API_KEY`) estiver setada — **fail-secure**.
  3. `/health` exibir `enforcement: "decision_only_locked"` em vez de só `aion_mode`.
  4. Container de produção POC: build separado (Dockerfile.poc-decision) sem o módulo `aion/proxy.py` (proxy LLM literalmente removido do binário).
- **Critério de aceite:** teste e2e: subir com `AION_MODE=poc_decision` + `OPENAI_API_KEY=sk-x` → boot exit. Subir com `AION_MODE=poc_decision` (sem creds) + `POST /v1/chat/completions` → 403 com `error.code=mode_violation`.
- **Status:** Reprovado.

### Achado novo: F-38 — Mesmo binário serve POC e Transparent — confusão de modo

- **Severidade:** S2
- **Área:** Arquitetura
- **O que está errado:** o mesmo container roda os dois modos. Operator pode flippar via env. Banco que assina POC Decision-Only não tem garantia de que uma atualização do AION não vai trazer Transparent ativado por engano (config drift, helm chart errado, etc.).
- **Correção:** ou imagens separadas (`aion-decision-only:tag` vs `aion-transparent:tag`), ou build flag em build-arg que **exclui** o código de `aion/proxy.py` (Transparent) do binário POC.
- **Status:** Reprovado (S2).

### Decisão revisada — terceira iteração

**Modo declarado de venda enterprise (POC Decision-Only):**

> **LIBERADO PARA POC SINGLE-TENANT CUSTOMER-SIDE DECISION-ONLY** com **5 fixes obrigatórios** (Bloco 1 reduzido para POC):
>
> 1. **F-37** — Enforcement técnico de "no LLM call" quando `AION_MODE=poc_decision` (rejeição em runtime + fail-secure no boot).
> 2. **F-06** — Sanitizar `event.data["input"]` antes de `emit()` e antes de qualquer ARGOS forward.
> 3. **F-07** — Persistir `cost_saved`/`tokens_saved` durável.
> 4. **F-10** — `/v1/explain` durável.
> 5. **F-22** — Decision contract incluir hashes para replay completo (em Decision-Only o contract é o produto).
>
> **F-15, F-16, F-36 NÃO são bloqueio para POC** (não aplicáveis ao modo Decision-Only).
> **F-38** vira blocker apenas se o cliente exigir imagem isolada.

**Modo Transparent (futuro, fora do POC enterprise restritivo):** mantém o veredito original — F-15, F-16, F-36 voltam a ser S1, e os 4 fixes da errata #1 + F-37 + F-38 todos são bloqueadores para "produção".

### Frase de encerramento revisada (3ª iteração)

> **POC Decision-Only liberada com contenção mínima.** Para banco, telecom e CISO restritivo (público-alvo declarado), o achado central é F-37: a promessa "AION não chama o LLM" precisa virar **enforcement técnico**, não confiança em configuração docker-compose. Sem isso, o produto pode até funcionar, mas não consegue **defender em auditoria do cliente** que nunca tocará as credenciais ou as conversas com o LLM.

---

## Errata #4 — Os 2 modelos de POC são opções legítimas, não default vs anomalia

4ª clarificação do dono do produto:
> "São 2 modelos de POCs com o AION decidindo e falando com o LLM e o AION só decidindo o cliente que fala com a LLM."

Confirmado em [docker-compose.poc-transparent.yml](docker-compose.poc-transparent.yml) e [docker-compose.poc-decision.yml](docker-compose.poc-decision.yml). Ambos são modos POC ofertados ao cliente:

| Modo | Quando usar (declarado) | Endpoint primário | Cliente expõe credencial LLM ao AION? | AION chama LLM? |
|---|---|---|:---:|:---:|
| **POC Decision-Only** | banco, telecom, CISO restritivo, primeiro contato enterprise | `POST /v1/decide` | ❌ Não | ❌ Não |
| **POC Transparent** | integração acelerada, cliente flexível, "zero code change" | `POST /v1/chat/completions` | ✅ Sim | ✅ Sim |

**Erro da Errata #3:** declarei Decision-Only como "o caminho crítico" e categorizei F-15/F-16/F-36 como `N/A em POC`. Errado — são **N/A apenas em POC Decision-Only**, mas **bloqueadores em POC Transparent**.

### Tabela de aplicabilidade dos achados por modo

| ID | Achado | POC Decision-Only | POC Transparent | Produção |
|---|---|:---:|:---:|:---:|
| F-03 | Audit secret opcional | **S1** | **S1** | **S1** |
| F-04 | Chave pública dev embutida | **S1** | **S1** | **S1** |
| F-05 | LICENSE_SKIP_VALIDATION env | S2 | S2 | S2 |
| F-06 | PII em event.data["input"] | **S1** | **S1** | **S1** |
| F-07 | cost_saved volátil | **S1** | **S1** | **S1** |
| F-09 | Preços hardcoded | S2 | S2 | S2 |
| F-10 | /v1/explain volátil | **S1** | **S1** | **S1** |
| F-12 | Chat anônimo silencioso | S2 | **S1** | **S1** |
| F-15 | Streaming sem cap | N/A | S2 | S2 |
| F-16 | Per-request cost cap ausente | N/A | **S1** | **S1** |
| F-22 | Decision contract sem hashes | **S1** (contract é o produto) | S2 | S2 |
| F-36 | Budget cap não-mandatório | N/A | **S1** | **S1** |
| F-37 | "AION não chama LLM" sem enforcement (em Decision-Only) | **S1** | N/A | — |
| F-38 | Mesmo binário serve os 2 modos (config drift risk) | S2 | S2 | S2 |

### Veredito por modo POC

#### POC Transparent — fixes obrigatórios

> **LIBERADO PARA POC TRANSPARENT** com 7 fixes obrigatórios:
>
> 1. **F-03** Audit secret obrigatório via `AION_PROFILE=production` (ou equivalente para POC).
> 2. **F-04** Chave pública não-fallback em build de produção.
> 3. **F-06** Sanitizar `event.data["input"]`.
> 4. **F-07** Persistir métricas executivas duráveis.
> 5. **F-10** `/v1/explain` durável.
> 6. **F-12** Sair do estado "chat anônimo silencioso" (boot abort se admin_key vazia).
> 7. **F-16 + F-36** Per-request cost cap + budget cap como pré-requisito de boot (controle de custo é promessa central; cliente vai ver na fatura OpenAI).
>
> **F-15** (streaming OOM) é S2 — não bloqueia POC, mas precisa de cap antes de produção.

#### POC Decision-Only — fixes obrigatórios

> **LIBERADO PARA POC DECISION-ONLY** com 6 fixes obrigatórios:
>
> 1. **F-37** Enforcement técnico de "no LLM call" quando `AION_MODE=poc_decision` (rejeição em runtime + fail-secure no boot).
> 2. **F-03** Audit secret obrigatório.
> 3. **F-04** Chave pública não-fallback em build de produção.
> 4. **F-06** Sanitizar `event.data["input"]`.
> 5. **F-07** Persistir métricas executivas duráveis.
> 6. **F-10** `/v1/explain` durável.
> 7. **F-22** Decision contract com hashes (em Decision-Only o contract **é o produto**) — listed como nice-to-have S2 se prazo apertar, mas idealmente fix obrigatório.

#### Comum aos dois POCs

> **F-17** (doc "702+ testes" vs 201 reais) e **F-19** (doc obsoleta sobre `aion/rbac.py`, `start.py`) **deveriam ser corrigidos antes de qualquer apresentação cliente** — não bloqueiam funcionamento mas matam credibilidade na primeira due-diligence.

### Frase de encerramento (4ª iteração)

> **Os dois modelos de POC estão liberados, com fixes específicos por modo.**
>
> POC Decision-Only (banco/telecom/CISO restritivo): 6 fixes — o central é F-37 (enforcement de "no LLM call").
>
> POC Transparent (integração acelerada): 7 fixes — o central é F-16+F-36 (controle de custo, já que AION está chamando o LLM com credenciais do cliente; sem cap, fatura do cliente fica exposta).
>
> Ambos compartilham: F-03 (audit), F-04 (license), F-06 (PII em telemetria), F-07 (métricas duráveis), F-10 (explain durável), F-17/F-19 (doc credibilidade).
>
> Em comum, o produto está **funcional para POC**, mas precisa **fechar o gap entre promessa e enforcement** antes de venda enterprise. Promessas centrais (no LLM call em Decision-Only; controle de custo em Transparent; PII não sai em ambos) precisam virar **garantia técnica do binário**, não confiança em configuração de docker-compose.

## O que muda

Achados rebaixados (problema de "tenants distintos" deixa de existir):

| ID | Severidade original | Severidade revisada | Motivo |
|---|:---:|:---:|---|
| **F-01** RBAC sem ownership operator↔tenant (delete) | S1 | **S2** | dentro do cliente, é higiene operacional intra-time, não breach cross-customer |
| **F-02** RBAC sem ownership operator↔tenant (read) | S1 | **S2** | idem |
| **F-11** `AION_REQUIRE_TENANT=false` default | S1 | **S3** | "default" tenant é ok em single-tenant; vira squad/projeto único |
| **F-13** `X-Aion-Actor-Role` sem JWT assinado | S1 | **S2** | console interno do cliente; risco se chave `console_proxy` vazar dentro da org |

Achados que **ganham peso** (em on-prem, defaults inseguros viram problema do cliente):

| ID | Severidade original | Severidade revisada | Motivo |
|---|:---:|:---:|---|
| **F-06** PII em `event.data["input"]` forwarded para ARGOS | S1 | **S1 (mantida)** | Promessa "única coisa que sai = metadados" é violada se ARGOS for ligado; o produto precisa **garantir tecnicamente** que `input` está sanitizado, mesmo com ARGOS opt-in. **Esse é o achado mais grave do veredito revisado.** |
| **F-16** Per-request cost cap ausente | S1 | **S1 (mantida) — agravada operacionalmente** | em on-prem, runaway de tokens vai direto na **fatura do cliente** com a chave LLM dele; promessa "controle de custo" violada por default off |
| **NEW F-36** `AION_BUDGET_ENABLED` desligado por default + Budget cap não-mandatório | — | **S1** | mesma raiz operacional: produto promete controle de custo, mas se cliente esquece de configurar, AION proxia tudo sem limite — fatura do cliente explode |
| **F-03** Audit chain forjável sem secret | S1 | **S1 (mantida)** | auditoria interna do cliente continua precisando ser válida; regulador externo pode exigir evidência |
| **F-04** Chave pública dev embutida | S1 | **S1 (mantida)** | a confiança do entitlement model é da **Baluarte como vendor**; perda dela queima credibilidade comercial |
| **F-05** `AION_LICENSE_SKIP_VALIDATION` | S2 | **S2 (mantida)** | risco: env esquecida em build de cliente |
| **F-07** `cost_saved_total` volátil (MENTIRA EXECUTIVA) | S1 | **S1 (mantida)** | dashboard executivo é mostrado para **gestor do cliente**; restart zera história — credibilidade do produto cai imediatamente |
| **F-10** `/v1/explain` volátil | S1 | **S1 (mantida)** | auditor interno do cliente espera explain de 30+ dias |
| **F-12** Chat anônimo silencioso (auth pass-through) | S1 | **S1 (mantida)** | no perímetro interno do cliente, qualquer aplicação interna que descobrir a porta 8080 do AION pode usar sem auth |
| **F-15** Streaming sem cap | S2 | **S2 (mantida)** | OOM no pod do cliente |
| **F-17** "702+ testes" (real 201) | S2 | **S2 (mantida)** | due-diligence do cliente fica embaraçosa |

## Placar de risco recalibrado

| Severidade | Quantidade revisada | Bloqueia? |
|---|:---:|:---:|
| **S0** | 0 | Sim |
| **S1** | **9** (F-03, F-04, F-06, F-07, F-10, F-12, F-16, F-36, e mantém F-NN dependendo de detalhes) | Sim |
| **S2** | ~22 (incluindo F-01, F-02, F-13, F-15, F-17, F-21, etc.) | Depende |
| **S3** | 6 (F-11, F-18, F-24, F-30, F-32, F-35) | Não imediato |
| **S4** | 0 | Não |

## RAD novos válidos (single-tenant declarado)

A declaração do usuário "AION fica dentro da estrutura do cliente, roda na arquitetura dele, única coisa que sai são metadados de telemetria" satisfaz parcialmente os critérios RAD:

| ID | Achado | Critério atendido | Critério ainda pendente | Status |
|----|--------|-------------------|------------------------|:------:|
| F-01, F-02 (cross-tenant RBAC) | declaração explícita do dono | dono nomeado (Baluarte/eduardosampaio1), evidência: memória `feedback_aion_deployment_model.md` + statement no audit | janela de revisão (caso AION vire SaaS), ADR formal | **RAD parcial** (severidade rebaixada para S2) |
| F-11 (require_tenant=false) | mesma declaração | mesmas | mesmas | **RAD parcial** (S3) |

Para virar **RAD pleno** ainda precisa: ADR markdown em `docs/decisions/0001-deployment-single-tenant-on-prem.md` com janela de revisão explícita.

## Decisão revisada

> **LIBERADO PARA POC SINGLE-TENANT ON-PREM** com 4 fixes obrigatórios (Bloco 1 reduzido):
>
> 1. **Sanitizar `event.data["input"]`** (F-06) — PII NÃO pode sair como texto cru, mesmo em metadados; isso é a promessa central do produto.
> 2. **Persistir `cost_saved` e métricas executivas** (F-07) — fonte única de truth via NEMOS Redis; `/v1/economics` lê de lá.
> 3. **Persistir `/v1/explain`** (F-10) em Redis stream com TTL ≥ retenção legal definida pelo cliente.
> 4. **Per-request cost cap + max_output_tokens cap + budget enabled by default** (F-16, F-36) — promessa "controle de custo" precisa ser ativa por default; não pode esperar o cliente "lembrar de configurar".

> **NÃO LIBERADO AINDA PARA PRODUÇÃO COM SLA ENTERPRISE** sem fechar também:
>
> 5. `AION_PROFILE=production` que torna `AION_SESSION_AUDIT_SECRET`, `AION_LICENSE_PUBLIC_KEY` (não-fallback), `AION_REQUIRE_CHAT_AUTH` + `AION_ADMIN_KEY` mandatórios e rejeita `AION_LICENSE_SKIP_VALIDATION=true` (F-03, F-04, F-05, F-12).
> 6. Documentação corrigida (F-17, F-18, F-19) — "702 testes" virou problema de credibilidade na primeira due-diligence.

> **Para evolução futura para SaaS multi-tenant**: voltar a tratar F-01, F-02, F-11, F-13 como S1 + obrigar RBAC ownership operator↔tenant.

## Frase de encerramento revisada

> **POC liberada com contenção mínima.** Para o modelo declarado (single-tenant on-prem com telemetria de metadados), o risco residual é **operacional** (configuração do deploy do cliente), não arquitetural. Mas as **4 promessas mais visíveis ao cliente** (PII não sai, controle de custo, métricas executivas, explainability) precisam virar **garantia técnica** — não dependerem da diligência operacional do cliente.

## Lições para auditorias futuras

1. **Verificar arquitetura de deployment ANTES de classificar severidades** — o mesmo código tem severidade radicalmente diferente em SaaS multi-tenant vs on-prem single-tenant.
2. **Consultar memória de feedback do usuário ANTES de aplicar lentes padrão** — `feedback_aion_deployment_model.md` já tinha essa orientação; ignorar memória custou ~1h de classificação inflada.
3. **Reler scope.md depois de cada fase**: a `scope.md` deste audit dizia "memória de sessões anteriores é referência de contexto, não substitui evidência" — interpretei isso como "ignorar memória de feedback", o que é o oposto do que a memória de feedback existe para fazer.
