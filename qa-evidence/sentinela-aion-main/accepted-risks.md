# Risco Aceito Documentado (RAD)

> **Atualizado em 2026-04-30 após errata** (ver [errata-and-recalibration.md](errata-and-recalibration.md)).

## RAD parciais válidos (após declaração explícita do dono do produto)

Statement do usuário/dono na sessão de auditoria: *"AION fica dentro da estrutura do cliente, roda na arquitetura dele, única coisa que sai são metadados de telemetria"* + memória `feedback_aion_deployment_model.md`.

| ID | Severidade | Achado | Decisão (link) | Dono | Janela | Gatilho de revisão | Status |
|----|:----------:|--------|----------------|------|--------|---------------------|:------:|
| RAD-1 | S2 (rebaixado de S1) | F-01, F-02 — RBAC sem ownership operator↔tenant | statement do dono + [feedback_aion_deployment_model.md] | Baluarte / @eduardosampaio1 | aberta enquanto modelo for single-tenant on-prem | "AION evolui para SaaS multi-tenant" → reclassificar | **Parcial** (falta ADR formal) |
| RAD-2 | S3 (rebaixado de S1) | F-11 — `AION_REQUIRE_TENANT=false` default | mesma decisão (default tenant é workspace lógico interno) | Baluarte / @eduardosampaio1 | aberta enquanto single-tenant | mesma | **Parcial** |
| RAD-3 | S2 (rebaixado de S1) | F-13 — `X-Aion-Actor-Role` sem JWT | mesma decisão (console é interno do cliente) | Baluarte / @eduardosampaio1 | aberta | "console_proxy precisa rodar fora do perímetro do cliente" → S1 e exigir JWT | **Parcial** |

**Para virar RAD pleno**, fechar:
- ADR `docs/decisions/0001-deployment-single-tenant-on-prem.md` com data, contexto, threat model considerado, consequências aceitas, gatilho de revisão.
- Reflexão na documentação cliente-facing (integration-guide, pilot-onboarding) explicitando o modelo.

## RAD rebaixados

Achados que poderiam ser RAD se decisão fosse formalizada. Hoje são **bloqueios**:

| ID | Tentou ser RAD | Critério ausente | Rebaixado para |
|----|----------------|------------------|----------------|
| F-11 | "AION é single-tenant on-prem" (declaração informal em memória de projeto) | Falta ADR/RFC formal; falta dono nomeado; falta gatilho de revisão. **A memória `feedback_aion_deployment_model.md` declara on-prem mas não substitui ADR.** | **Bloqueio S1** (em modo multi-tenant) |
| F-13 | Documentação alega "RBAC implementado" e console_proxy é design intencional | Falta documento que descreva ameaça compreendida + mitigação (ex: "console_proxy só roda em rede privada; vazamento da chave = breach") | **Bloqueio S1** |
| F-14 | `/health` exposto público é prática comum K8s | Sem documento explícito tratando o conteúdo de license_id/expiry como PUBLIC | **Bloqueio S2** |
| F-21 | Behavior dial é prompt injection by design | Sem ADR formalizando "Behavior Profile != parametric dial" + posicionamento de marketing alinhado | **Bloqueio S2** |
| F-24 | Pin de dependência é decisão de operação, não de código | Sem doc indicando "uso de uv lock" / política de upgrade | **Bloqueio S3** |
| F-15 | Streaming buffer é tradeoff conhecido (safety > UX) — README admite | Falta cap explícito + ADR que aceite limite (ex: "max 200k tokens output") | **Bloqueio S2** |
| F-25 | Cache LRU local é "fast path" intencional | Falta ADR sobre cache distribuído como roadmap | **Bloqueio S2** |
| F-23 | `rotate-keys` é "best-effort" para multi-replica | Falta runbook de rotação coordenada + dual-secret window | **Bloqueio S2** |
| F-09 | Preços hardcoded é "snapshot" | Falta ADR + processo de refresh + alerta de drift | **Bloqueio S2** |

## Critério para promover para RAD válido

Para que um dos itens acima vire **RAD válido** (e não bloqueio), entregar TODOS os 6:

1. **Decisão explícita** — ADR (`docs/decisions/NNNN-*.md`) ou RFC com data, contexto, consequências aceitas.
2. **Dono nomeado** — pessoa ou squad (ex: "Backend Squad — @maintainer").
3. **Janela definida** — sprint/release/data até quando o risco é tolerado.
4. **Critério de revisão** — gatilho mensurável (ex: "ao atingir 5 tenants pagantes", "ao alcançar US$ 50k MRR").
5. **Limite de severidade** — RAD nunca vale para S0; para S1 exige aprovação executiva citada por nome.
6. **Evidência da decisão** — link no audit (ADR markdown) consultável.

## Notas

- O audit **não invalida** a estratégia do projeto. Vários gaps são razoáveis para uma fase POC. O ponto é que `pre-launch enterprise` não tolera os mesmos atalhos.
- A memória `project_aion_15.md` e a memória `feedback_aion_deployment_model.md` indicam decisões de design, mas **memórias de sessão Claude não são ADRs auditáveis** e não satisfazem critério 6.
