# Findings V2 — pós-fixes

Apêndice da auditoria original. Lista os achados **novos** introduzidos pelos fixes, e o status atualizado de cada finding original.

---

## 🔴 CRÍTICOS (0)

Todos os 4 originais foram fechados:

| ID | Status | Evidência |
|---|---|---|
| C1 — `/v1/models` schema | ✅ Fechado funcionalmente (com efeito colateral N1+N2) | curl retorna 4 modelos com schema completo |
| C2 — setBehavior reset | ✅ Fechado | merge funciona; `extra="forbid"` retorna 422 em campo desconhecido |
| C3 — `/v1/killswitch` shape | ✅ Fechado | `{killswitch_active, reason, expires_at}` |
| C4 — Proxy auth gate | ⚠ Parcialmente fechado (vide N6) | gate em produção ok; fail-open em dev |

---

## 🟠 ALTOS (4 novos / herdados)

### [N1] — Catálogo de modelos hardcoded, não reflete config real

**Componente:** `aion/routers/observability.py:371-449`

**Risco:** O endpoint `/v1/models` retorna sempre os mesmos 4 modelos curados (gpt-4o-mini, gpt-4o, claude-sonnet, gemini-flash) independentemente de quais credenciais o tenant tem configuradas. Todos com `status="active"` (exceto gemini-flash, que é `"fallback"` hardcoded).

**Condição de disparo:** Sempre que o console abre `/routing` ou `/intelligence`. O frontend mostra todos os 4 modelos como disponíveis.

**Impacto:** Cliente que tem só credencial OpenAI vê Claude e Gemini como ativos. Tenta usar (mudando regra de roteamento, escolhendo modelo manual) e o NOMOS/proxy falha porque não tem chave Anthropic/Google. UX promete o que o backend não entrega.

**Mitigação interna:** docstring do handler reconhece que é placeholder — "future improvement can drive this from a YAML/env catalog".

---

### [N2] — `status` do modelo não reflete circuit breaker do NOMOS

**Componente:** `aion/routers/observability.py:371-449`

**Risco:** O `status` retornado é hardcoded (`"active"` ou `"fallback"`). O frontend tem lógica em `routing-page.tsx:382-384` para derivar a saúde do provider via `m.status === "error"` — mas o backend nunca retorna esse valor.

**Condição de disparo:** Provider externo (OpenAI, Anthropic) cai. NOMOS marca o circuit breaker como aberto. O `/v1/models` continua retornando `"active"`.

**Impacto:** Página de Provedores mostra "Ativo" durante incidente real. Operador descobre tarde. Observability operacional quebrada na superfície que mais importa.

---

### [N6] — Proxy auth gate fail-open em qualquer NODE_ENV ≠ "production"

**Componente:** `aion-console/src/app/api/proxy/[...path]/route.ts:65-75`

**Risco:** O gate só retorna 401 se `process.env.NODE_ENV === "production"`. Em desenvolvimento, staging, ou qualquer ambiente onde NODE_ENV não esteja explicitamente setado para "production", o código apenas faz `console.warn` e segue a requisição com a `AION_API_KEY` (admin) injetada via `if (API_KEY) { Authorization: Bearer ... }`.

**Condição de disparo:** 
1. Deploy em VM bare-metal usando `node server.js` sem env file → NODE_ENV undefined.
2. PM2 sem `--node-env production`.
3. systemd unit que esquece `Environment=NODE_ENV=production`.
4. Container com env var sobrescrita em dev.

**Impacto:** Em qualquer um dos cenários acima, qualquer requisição HTTP a `/api/proxy/v1/*` chega ao backend AION com chave admin sem autenticação prévia. Equivale a "modo aberto silencioso". A intenção era fail-closed em produção; o que ficou é fail-open por padrão e fail-closed como exceção.

**Padrão correto:** o oposto — gate ON por padrão, opt-in explícito para dev (`AION_PROXY_DEV_BYPASS=true`).

---

### [A4-resíduo] — `ModelInfo` continua com 7 campos ricos que o backend reporta como hardcode

(Mesma observação de N1+N2, mas vista do lado frontend. Os tipos estão alinhados — o problema é a fonte da verdade.)

---

## 🟡 MÉDIOS (3)

### [N5] — Killswitch é volatile (perdido em restart do processo)

**Componente:** `aion/pipeline.py:135-141`

**Risco:** As 3 variáveis (`_safe_mode`, `_safe_mode_reason`, `_safe_mode_expires_at`) vivem só na memória do processo. Restart do container (deploy, OOM kill, autoscale rolling) **desativa o killswitch silenciosamente** mesmo que TTL ainda fosse longo.

**Condição de disparo:** Killswitch ativo + qualquer event que mate o processo: deploy, container restart, crash, scale event.

**Impacto:** Operador ativa killswitch em incidente. AION reinicia (deploy programado, OOM, etc). Killswitch desativa sozinho. Tráfego volta a ser processado durante incidente em curso. Operador não sabe.

**Mitigação:** persistir estado no Redis (já usado para Behavior). Pequeno fix.

---

### [M1-herdado] — Dead code: `getTenantSettings` / `updateTenantSettings`

Continua. Backend não tem `/v1/tenant/{tenant}/settings`, frontend não chama essas funções, mas continuam exportadas.

---

### [M2-herdado] — `extra="forbid"` aplicado SÓ ao `BehaviorConfig`

Outros endpoints (`/v1/overrides`, `/v1/modules/{name}/toggle`) seguem usando `body.get(...)` que aceita campos extras silenciosamente. Não tem outros Pydantic models de write na API atual, mas o padrão não foi padronizado.

---

### [M3-herdado] — `useApiData` não distingue "API ok mas vazia" de "API offline"

Não foi alterado. Continua retornando `isDemo=false` quando o fetcher resolve com `[]` ou shape inesperado.

---

## 🟢 BAIXOS (5)

### [N3] — `safe_mode_state` property tem efeito colateral

`aion/pipeline.py:185-201` — chama `deactivate_safe_mode()` (que emite log de transição) durante uma leitura. Properties em Python deveriam ser puras. Confusão para desenvolvedor.

### [N4] — Race condition GET-then-PUT em `setBehavior`

`aion/routers/control_plane.py:163-166` — sem lock nem optimistic concurrency. Dois clientes editando simultaneamente: last-write-wins.

### [N7] — Regex do matcher de `proxy.ts` é frágil

`aion-console/src/proxy.ts:28` — `login` no negative-lookahead exclui também `login-signup`, `loginstuff` se essas rotas forem criadas. Não é bug hoje.

### [B1-herdado] — Endpoints de cliente não usados pelo console

`/v1/decide`, `/v1/chat/completions`, `/v1/chat/assisted`, `/v1/decisions` — intencional, são para a aplicação cliente.

### [B2-herdado] — Endpoints backend sem consumidor

`/v1/session/{id}/audit/export`, `/v1/collective/packs`, `/v1/approvals/{id}` (single GET), `/metrics`, `/ready`, `/version`, `/v1/metrics/tenant/{tenant}` — gap de feature, não bug.
