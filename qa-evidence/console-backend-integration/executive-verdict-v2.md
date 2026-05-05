# Veredicto V2 — Pós-fixes C1 a A4

**Auditor:** Porteiro do Inferno — re-auditoria
**Data:** 2026-05-04 (pós-fixes)
**Escopo:** verificar se os 8 fixes (C1–A4) realmente fecharam os achados originais E procurar regressões introduzidas pelas mudanças.

---

## VEREDICTO: **APTO COM RESTRIÇÕES**

**Score: 7.5/10** (subiu de 6/10)

Os 4 críticos da auditoria original foram fechados de forma verificável (eu li o código e bati com os curl tests). **MAS dois deles (C1 e C4) ressurgiram em forma menor, como ALTOs** — porque a forma escolhida para fechar deixou um efeito colateral. Esses ALTOs novos são gerenciáveis se documentados e monitorados, o que justifica subir para "APTO COM RESTRIÇÕES" em vez de "APTO PARA PRODUÇÃO".

Para virar "APTO PARA PRODUÇÃO" plena: 4 ALTOs precisam de fix (estimativa 8–12h dev), e os 3 MÉDIOs herdados precisam ir para o sprint seguinte.

---

## Status dos achados originais (após fixes)

| ID | Antes | Depois | Como verifiquei |
|---|---|---|---|
| **C1** Models schema | 1 modelo, sem capabilities | ✅ FECHADO funcionalmente. **MAS** virou N1+N2 (catálogo é placeholder hardcoded) | curl `/v1/models` retorna 4 modelos com schema completo + leitura de `aion/routers/observability.py:371-449` |
| **C2** setBehavior reset | resetava todos a default | ✅ FECHADO. Merge funciona. `extra="forbid"` retorna 422 em campo desconhecido | curl PUT `{economy:80}` → economy=80 persistido + PUT `{objectivity:70}` depois → economy=80 PRESERVADO + leitura de `aion/routers/control_plane.py:150-172` |
| **C3** /v1/killswitch GET shape | `{safe_mode}` | ✅ FECHADO. `{killswitch_active, reason, expires_at}` | curl confirma + leitura de `aion/routers/control_plane.py:25-79` |
| **C4** Proxy auth gate ausente | sem gate | ⚠ **PARCIALMENTE FECHADO**. Gate em produção OK, mas fail-open em dev — virou N6 | leitura de `aion-console/src/app/api/proxy/[...path]/route.ts:60-75` |
| **A1** getBehavior envelope | retornava `{tenant, behavior}` tipado errado | ✅ FECHADO. Desempacota e retorna `BehaviorDial` populado | leitura de `aion-console/src/lib/api/behavior.ts:28-31` |
| **A2** BehaviorDial ↔ BehaviorConfig disjuntos | só 3 de 7 batiam | ✅ FECHADO. Backend agora aceita os 9 campos (5 originais + 4 do front) | leitura de `aion/metis/behavior.py:27-57` |
| **A3** PUT /v1/killswitch sem TTL | `duration_seconds` ignorado | ✅ FECHADO. Pipeline armazena `_safe_mode_expires_at`, lazy auto-deactivate em `is_safe_mode()` | curl com `duration_seconds:60` retornou `expires_at` populado + leitura de `aion/pipeline.py:135-201` |
| **A4** ModelInfo campos faltantes | só id/provider/type | ✅ FECHADO funcionalmente. Mesma observação de C1 — virou N1 | (mesma evidência de C1) |

**Pendentes da auditoria anterior (não tocados):**
- M1 Dead code `getTenantSettings`/`updateTenantSettings` — continua
- M2 `extra="forbid"` foi aplicado SÓ ao BehaviorConfig — outros endpoints continuam tolerantes
- M3 `useApiData` não distingue empty vs offline — continua

---

## Achados NOVOS (N1–N7) introduzidos pelas mudanças

### 🟠 N1 — Catálogo de modelos é placeholder hardcoded

**Componente:** `aion/routers/observability.py:371-449`
**Risco:** A lista retornada é **fixa** com 4 modelos (gpt-4o-mini, gpt-4o, claude-sonnet, gemini-flash), todos com `status="active"` (e gemini-flash como `"fallback"`), independentemente do que o tenant tem realmente configurado/credenciado.
**Cenário real:** Cliente PoC com SÓ credenciais OpenAI vê Claude e Gemini como ativos no `/routing`. Tenta rotear, NOMOS falha porque não tem credenciais Anthropic/Google.
**Severidade: ALTO** — engana o usuário sobre o que está disponível.
**Mitigação documentada:** docstring reconhece "future improvement can drive this from a YAML/env catalog (see roadmap)".

### 🟠 N2 — Status `active`/`fallback` não reflete circuit breaker real

**Componente:** mesmo arquivo
**Risco:** O `status` de cada modelo é hardcoded. O console tem lógica para derivar saúde do provider via `m.status === "error"`, mas o backend NUNCA retorna esse valor. O circuit breaker do NOMOS pode estar marcando OpenAI como degradado e a tela "Provedores configurados" continua mostrando "Ativo".
**Cenário real:** Provider cai, console mente sobre o estado. Operador descobre em incidente, não em proativo.
**Severidade: ALTO** — observability operacional quebrada.

### 🟠 N6 — Proxy auth gate é fail-open em dev / misconfig

**Componente:** `aion-console/src/app/api/proxy/[...path]/route.ts:66-75`
**Risco:** O gate só retorna 401 se `process.env.NODE_ENV === "production"`. Em qualquer outro caso (dev, staging mal-configurado, NODE_ENV undefined em VM bare-metal), o código apenas faz `console.warn` e continua a requisição com a `AION_API_KEY` (admin) injetada.
**Cenário real:** Deploy de produção com NODE_ENV não setado por descuido (ex: PM2 sem `--node-env`, systemd sem env file). Gate fica permissivo. Brecha de auth completa.
**Severidade: ALTO** — fail-open por design.
**Padrão correto:** fail-closed por padrão, opt-in explícito para dev (`AION_PROXY_DEV_BYPASS=true`).

### 🟡 N5 — Killswitch state é volatile (perdido em restart)

**Componente:** `aion/pipeline.py:135-141`
**Risco:** `_safe_mode`, `_safe_mode_reason`, `_safe_mode_expires_at` vivem só na memória do processo. Restart do container (deploy, crash, OOM) **desliga o killswitch silenciosamente**, mesmo que TTL ainda fosse longo.
**Cenário real:** Operador ativa killswitch para incidente em andamento. AION crasha (ou faz autoscale rolling restart). Killswitch desativa sozinho. Tráfego volta a ser processado durante incidente. Operador não sabe.
**Severidade: MÉDIO** (já era debt antes, mas agora com TTL ficou explícito).
**Mitigação:** persistir estado no Redis (já usado para Behavior). Pequeno fix.

### 🟢 N3 — `safe_mode_state` property tem efeito colateral

**Componente:** `aion/pipeline.py:185-201`
**Risco:** Property em Python deveria ser leitura pura. A nossa chama `deactivate_safe_mode()` se TTL expirou — gera log de transição como efeito de uma leitura. Confunde quem lê.
**Severidade: BAIXA** (estilo + sutil; não quebra nada).

### 🟢 N4 — Race condition no merge de `setBehavior`

**Componente:** `aion/routers/control_plane.py:163-166`
**Risco:** Padrão GET-then-PUT sem optimistic concurrency. Dois clientes editando simultaneamente: last-write-wins.
**Severidade: BAIXA** (multi-tenant single-user no console, baixa probabilidade).

### 🟢 N7 — Regex do matcher de `proxy.ts` é frágil

**Componente:** `aion-console/src/proxy.ts:28`
**Risco:** `/login` no regex exclui também `/login-signup`, `/loginstuff` (lookahead substring). Hoje não tem rotas assim, mas se alguém criar `/logout` ou `/login/help`, comportamento inesperado.
**Severidade: BAIXA** (futuro, não atual).

---

## Avaliação por componente (atualizada)

| Componente | Antes | Depois | Justificativa |
|---|---|---|---|
| **Sidebar (mode badge)** | 9/10 | 9/10 | Sem mudança |
| **Mapa de roteamento (novo)** | 8/10 | 8/10 | Sem mudança |
| **/operations** | 7/10 | 7/10 | Sem mudança |
| **/sessions** | 8/10 | 8/10 | Sem mudança |
| **/estixe (Proteção)** | 5/10 | **8/10** | KS GET agora reflete estado real (C3). Banner correto. |
| **/routing** | 3/10 | **7/10** | Models e setBehavior funcionam. **MAS** placeholder de modelos (N1, N2) impede 9/10 |
| **/settings (aba Controles avançados)** | 4/10 | **8/10** | Kill Switch funciona corretamente. Activate/deactivate roundtrip ok. |
| **/intelligence** | 9/10 | 9/10 | Sem mudança |
| **/budget** | 9/10 | 9/10 | Sem mudança |
| **/admin** | 8/10 | 8/10 | Sem mudança (M1 ainda) |
| **/collective** | 9/10 | 9/10 | Sem mudança |
| **/shadow** | 9/10 | 9/10 | Sem mudança |
| **/reports** | 9/10 | 9/10 | Sem mudança |
| **Proxy auth** | 4/10 | **6/10** | Gate em route.ts + proxy.ts excluindo /api/proxy/*. **MAS** N6 (fail-open em dev/misconfig) impede mais |

---

## Resumo por severidade (V2)

| Severidade | Antes | Depois | Delta |
|---|---|---|---|
| 🔴 **CRÍTICO** | 4 | **0** | -4 ✓ |
| 🟠 **ALTO** | 4 | **4** | (ressurgência de C1/C4 como N1, N2, N6) |
| 🟡 **MÉDIO** | 3 | **3** | (N5 novo + M1, M2 parcial, M3 herdados) |
| 🟢 **BAIXO** | 2 | **5** | (N3, N4, N7 novos + B1, B2 originais) |

---

## Conclusão

Os 8 fixes valeram a pena — **0 críticos é um resultado real** que tira o produto de "POC apenas". As telas que estavam quebradas (routing, settings, estixe) agora funcionam.

**Mas a forma como os fixes foram implementados deixou 3 ALTOs novos**:
- **N1+N2**: o catálogo de modelos é placeholder, não fonte da verdade — engana o usuário sobre disponibilidade real
- **N6**: o auth gate é fail-open em qualquer ambiente que não seja `NODE_ENV=production` exato

Esses 3 ALTOs são **gerenciáveis com documentação + monitoramento** (daí "APTO COM RESTRIÇÕES"), mas não são "production-grade clean".

**Próxima janela** (8–12h dev): N1+N2 (catálogo real configurável), N6 (fail-closed default), N5 (persistir killswitch em Redis).
