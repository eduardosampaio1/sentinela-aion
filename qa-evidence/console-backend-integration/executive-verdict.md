# Veredicto — Console ↔ Backend (auditoria de integração)

**Auditor:** Porteiro do Inferno
**Data:** 2026-05-04
**Escopo:** **único** — verificar se o frontend (`aion-console`) está realmente conectado com o backend (`aion`). Não auditei segurança, lógica de negócio nem banco; só contratos de API e wiring entre as duas pontas.

---

## VEREDICTO: **NÃO APTO PARA PRODUÇÃO — POC APENAS**

**Score: 6/10**

A arquitetura de integração está correta — proxy server-side, tenant header, auth headers, transformers para normalizar contratos. Mas **4 contratos de endpoint estão quebrados de forma silenciosa** em telas que o usuário usa hoje (mapa de roteamento, kill switch, dial de comportamento). O resto (~25 endpoints) funciona como esperado.

A diferença entre "POC" e "produção" aqui não é arquitetural — é localizada. Os 4 críticos são corrigíveis em um sprint sem refatoração estrutural. Mas, no estado atual, **se um cliente real abrir o console, ele vê dados defasados sem aviso e clica em botões que não fazem o que dizem fazer.**

---

## Resumo por severidade

| Severidade | Quantidade | Impacto principal |
|---|---|---|
| 🔴 **CRÍTICO** | 4 | Telas operacionais mostram estado errado / botões sem efeito |
| 🟠 **ALTO** | 4 | Campos faltantes no contrato, envelope errado, leituras quebradas |
| 🟡 **MÉDIO** | 3 | Dead code, falta de fail-fast em validação Pydantic, demo banner não dispara |
| 🟢 **BAIXO** | 2 | Endpoints de cliente não usados pelo console (intencional) |

**Total de endpoints catalogados:** 30 chamadas do frontend × 22 rotas correspondentes no backend.

---

## Bloqueadores críticos

### C1 — `/v1/models` retorna 1 modelo com schema incompleto
Backend devolve `[{id, provider, type}]` (apenas o `default_model`). Frontend exige `capabilities` array, `cost_input_per_1m`, `cost_output_per_1m`, `latency_ms`, `max_tokens`, `status`. O `isModelInfoLike` filtra TODOS os modelos do backend, retorna `[]`, e o `useApiData` não dispara o demo banner (não foi erro). **`/routing` mostra grid vazio sem aviso.**

### C2 — `setBehavior({economy: N})` reseta TODOS os dials para default
Frontend envia `{economy: number}`. Backend `BehaviorConfig` não tem `economy` (tem `cost_target` string + `density/objectivity/explanation/formality` int). Pydantic v2 com `extra="ignore"` (default) descarta `economy` em silêncio e cria a config com TODOS os defaults (50, 50, "medium", 50, 50). **Cada clique em "Salvar prioridade" zera o dial de comportamento. O usuário não recebe erro.**

### C3 — `/v1/killswitch` GET retorna `{safe_mode}`, frontend lê `killswitch_active`
Backend: `{"safe_mode": boolean}`. Frontend: `setKsActive(res.killswitch_active)` → `undefined` → React trata como falsy → **a UI sempre mostra "Kill Switch INATIVO" mesmo quando o backend está em safe_mode.** O usuário não consegue saber se o sistema está parado pelo console.

### C4 — Proxy `/api/proxy/*` não bloqueia requests não autenticados
`route.ts` chama `auth()` mas só usa o resultado para injetar headers de actor — **não há `if (!session) return 401;`**. A `AION_API_KEY` é injetada server-side independentemente. Qualquer request HTTP direto a `/api/proxy/...` chega ao backend com chave de admin. Mitigação parcial: o middleware do Next.js pode estar bloqueando — não verifiquei. **Se não estiver, é vetor de bypass de auth completo.**

---

## Avaliação por componente

| Componente | Nota | Justificativa |
|---|---|---|
| **Sidebar (mode badge)** | 9/10 | `/health` retorna `aion_mode`, `executes_llm`, `telemetry_enabled`, `collective_enabled`, `active_modules` — match perfeito. |
| **Mapa de roteamento (novo)** | 8/10 | `/health.active_modules` correto. Risco baixo: se backend não tiver módulo "metis" no array, frontend não mostra o estado correto (mas hoje só temos estixe/nomos visíveis). |
| **/operations** | 7/10 | `toggleModule()` ↔ `/v1/modules/{name}/toggle` match perfeito. `getStats()` ↔ `/v1/stats` ok com fallback. |
| **/sessions** | 8/10 | Sessions list + audit trail ✓. Approvals ✓. |
| **/estixe (Proteção)** | 5/10 | Suggestions ✓, reload ✓, overrides ✓, **kill switch quebrado (C3)**. |
| **/routing** | 3/10 | **Models endpoint quebrado (C1)**. **setBehavior quebrado (C2)**. Topology map ✓. |
| **/settings** | 4/10 | Rotate keys ✓. **Kill switch quebrado (C3)** na nova aba "Controles avançados". |
| **/intelligence** | 9/10 | Overview, intents, threats, threat-feed — todos ok. |
| **/budget** | 9/10 | Budget status + economics — ok com transformer dedicado. |
| **/admin** | 8/10 | Audit, rotate keys, LGPD delete — ok. `getTenantSettings` é dead code. |
| **/collective** | 9/10 | Browse, install, promote — ok. |
| **/shadow** | 9/10 | Calibration get/promote/rollback — ok. |
| **/reports** | 9/10 | Executive report + schedule — ok (suporta JSON e PDF binary). |
| **Proxy auth** | 4/10 | **Falta gate de unauthenticated (C4)**. Forwards de header ok. Streaming ok. |

---

## Conclusão

O console fala com o backend em quase tudo — **mas as 3 telas mais visíveis no demo (routing, settings, estixe) têm contratos rotos** que o usuário não vê quebrar (sem erro visível, sem demo banner). Isso é pior do que falha total: passa despercebido em QA manual.

**Para virar produção:** corrigir os 4 críticos (estimativa: 6–10 horas de dev + teste). Os ALTOs e MÉDIOs podem ir para o sprint seguinte.

**Para manter como POC:** o estado atual roda. Mas não venda os dials de comportamento (C2) nem o kill switch via console (C3) sem corrigir.
