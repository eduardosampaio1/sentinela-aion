# Pré-0 — Escopo Declarado

## Modo
`pre-launch` (a branch `main` é alvo declarado de "produção / cliente").

## Time-box
~2h de leitura estática. Ultrapassou → marcar `AUDIT INCOMPLETO` no veredito.

## Profundidade
Blast-radius nível 2 (módulo direto + importadores diretos + contratos expostos).

## Restrições de evidência (pontos cegos declarados)
- Read-only sobre o repositório clonado em `D:\projetos\sentinela-aion-main` (commit `8af7d97`).
- **Sem rodar testes** (sem ambiente Python configurado para isso aqui — risco de instalar dependências pesadas como `faiss-cpu`, `sentence-transformers`).
- **Sem hits em ambiente real** (sem Redis, sem LLM upstream, sem Supabase de teste).
- **Sem fuzzing nem load test**.
- **Sem instalar dependências** novas no host.
- **Sem auditoria do `aion-console` (Next.js) em profundidade** — frontend recebe avaliação de superfície apenas (verifico contratos, env vars, secrets expostos; não auditoria heurística de UI/UX).
- A pasta `aion-console/copy/` e `design-system/` recebem inspeção rasa.
- `benchmarks/` é tratado como suporte, não código de produção.

## Out-of-scope explícito
- Repositório paralelo `D:\projetos\sentinela-aion` (branch `develop` com alterações locais) — fora deste audit.
- Memória de sessões anteriores (`project_aion_*.md`) é referência de contexto, **não substitui evidência**.
- `aion-console/.next/`, `node_modules/`, `__pycache__/`, `.runtime/`.
- Documentação em PT-BR fora dos arquivos `docs/` enumerados.

## Tipo de projeto identificado
Anchor primário: **Backend service / API standalone** (FastAPI proxy OpenAI-compatible).
Anchor secundário: **ML/AI system** — invoca LLMs, faz embedding/classificação (`sentence-transformers`, FAISS), tem behavior dial e roteamento de modelo. **Sub-fase 4.1 (AI/LLM Risk Bundle) aplicável.**
Anchor terciário: **Frontend SPA** para `aion-console/` (Next.js), tratado em superfície.

## Promessas auditadas (extraídas de README, .env.example, PRODUCTION_CHECKLIST.md)

1. **Isolamento multi-tenant por header `X-Aion-Tenant`** — config, budget, overrides e dados de cada boundary não devem cruzar.
2. **Licença Ed25519 offline com Trust Guard** — sem licença válida, AION não inicia. Sem phone-home.
3. **Trilha de auditoria hash-chained HMAC-SHA256** — assinada com `AION_SESSION_AUDIT_SECRET`, tamper-evident.
4. **Bypass de saudações/despedidas zero-token (ESTIXE)** — economia de tokens prometida; precisa medir.
5. **Bloqueio de prompt injection e PII** — política aplicada antes de chamar o LLM.
6. **Roteamento NOMOS** decide modelo por complexidade/custo/latência sem ML pesado.
7. **METIS** comprime prompt e otimiza resposta — economia mensurável.
8. **Compliance LGPD**: `/v1/data/{tenant}` apaga, retenção controlada por `AION_TELEMETRY_RETENTION_HOURS`.
9. **Budget cap por tenant** — `PUT /v1/budget/{tenant}` impede gasto além do limite (Cost engineering).
10. **PII nunca sai do ambiente do cliente** — telemetria externa só com DPA assinado, modo Shadow opt-in.
11. **702+ testes, 0 falhas** (claim explícita do PRODUCTION_CHECKLIST.md).
12. **Performance**: ≥99.5% sucesso; p95 < 500ms; ≥100 RPS/réplica; attack block rate ≥95%; FP <0.1%.
13. **Fail-mode configurável**: `open` (graceful) ou `closed` (compliance).
14. **Kill switch global** (`AION_SAFE_MODE=true`) bypassa tudo.
15. **Decisão explicável**: `/v1/explain/{request_id}` reconstrói por que cada decisão foi tomada.

## Boundary de isolamento adotado
"tenant" = identificador passado via header `X-Aion-Tenant` (com fallback para `default` se `AION_REQUIRE_TENANT=false`).

## Tradução de termos para este audit
- "Entrypoint" = endpoint HTTP exposto pelo FastAPI (`/v1/...`, `/health`, `/ready`, `/metrics`) + scripts CLI (`aion`, `python -m aion.cli`).
- "Boundary" = `tenant` (header) — multi-tenant declarado, embora memória diga "AION é single-tenant on-prem"; **veremos se o código entrega multi-tenant real ou só o tema**.
- "Dashboard executivo" = `/v1/intelligence/{tenant}/overview`, `/v1/economics`, `/v1/stats` + console Next.js.

## Critérios de saída
Audit termina ao concluir todas as 9 fases ou ao atingir time-box. Se faltar evidência, status fica `IMPOSSÍVEL VALIDAR COM EVIDÊNCIA ATUAL`.
