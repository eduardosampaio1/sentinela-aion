# Test Gaps — Console ↔ Backend

Caminhos críticos do contrato entre frontend e backend que **não têm cobertura automatizada** e dependem de QA manual hoje.

---

## 1. Contract tests entre frontend e backend (ZERO)

**Risco:** os 4 críticos desta auditoria existem porque ninguém valida o contrato em CI. Cada lado evolui independentemente.

**Recomendação:**
- Adicionar suite de contract tests em `aion-console/__tests__/api-contract/` que:
  - Faz request real ao backend (via mock de `/api/proxy` ou contra container de teste)
  - Valida o shape da resposta com Zod ou TypeBox
  - Roda no CI da console em cada PR
- OU usar Pact/Schemathesis no backend para gerar OpenAPI e validar consumers

**Endpoints com risco mais alto:**
- `/v1/models` (C1)
- `/v1/behavior` (C2, A1, A2)
- `/v1/killswitch` (C3, A3)
- `/v1/stats` (transformer já lida com fields ausentes — mas se backend mudar nomes, ninguém pega)

---

## 2. Página `/routing` — cenário "modelos vazios"

**Risco:** o type guard de `getModels()` filtra silenciosamente. Se o backend retornar payload novo no futuro, o filtro pode esconder dados reais.

**Cobertura ausente:**
- Teste de componente que renderiza `routing-page.tsx` com `getModels()` mockado para retornar `[]` e verifica que existe alguma sinalização visual ("0 modelos configurados") ao invés de grid vazio.
- Teste de `isModelInfoLike` com payloads reais do backend (gravar um payload de exemplo em fixture).

---

## 3. Slider de "Prioridade Economia ↔ Qualidade" → backend

**Risco:** já citado em C2. Hoje é zero teste.

**Cobertura ausente:**
- Unit test em `behavior.ts:setBehavior` validando que o body enviado tem campos válidos do `BehaviorConfig`.
- Backend integration test que valida que `setBehavior({economy: 80})` resulta em config persistida com `economy=80` (vai falhar hoje — bom, deveria).

---

## 4. Kill switch — fluxo completo

**Risco:** C3 e A3. Sem teste, regressões aqui passam pelo QA visual.

**Cobertura ausente:**
- E2E (Playwright/Cypress): activate KS via UI → verifica que banner vermelho aparece + outras telas refletem estado parado → desativa → banner some.
- Backend test: PUT/GET/DELETE com TTL — valida que `expires_at` é respeitado e killswitch desativa automaticamente após TTL.

---

## 5. Proxy auth gate

**Risco:** C4. Sem teste, não temos como detectar regressão se alguém remover o middleware.

**Cobertura ausente:**
- Integration test: `fetch('/api/proxy/v1/stats')` sem cookie de sessão deve retornar 401 (não 200).
- Smoke test em CI cobrindo: logged-in vs logged-out vs expired-session.

---

## 6. Páginas que dependem de mock fallback

**Risco:** quando `useApiData` cai em fallback (backend offline), a UI mostra mock. **Hoje não tem teste validando que o mock é coerente com o tipo real.** Se o backend mudar o shape e o frontend não atualizar o mock, o usuário em modo demo pode ver dados visualmente diferentes do real.

**Cobertura ausente:**
- Snapshot test em cada página com `enabled=false` (modo demo forçado) capturando o render.
- Type-check do mock contra `lib/types.ts` em CI (alguns mocks são `as Stats` e perdem checagem real).

---

## 7. Páginas afetadas por `aion_mode` do backend

**Risco:** mapa de roteamento (recém-implementado), badge no sidebar, hint na página `/operations`. Se o backend retornar valor inesperado (`aion_mode: "future_mode_xyz"`), o frontend tem fallback para `not_configured`. Mas não há teste validando isso.

**Cobertura ausente:**
- Teste do componente `RoutingTopologyMap` com cada valor possível de `aion_mode` (poc_decision, poc_transparent, full_transparent, decision_only, not_configured, undefined, "garbage_value").
- Verificar que para cada modo, as edges visíveis mudam corretamente (response leg só aparece em transparent).

---

## 8. `useApiData` — diferença "API vazia" vs "API offline"

**Risco:** M3. Hoje os dois cenários são indistinguíveis para o usuário.

**Cobertura ausente:**
- Teste do hook isoladamente:
  - Caso A: fetcher rejeita → `isDemo=true`, dados=fallback.
  - Caso B: fetcher resolve com `[]` ou `{}` vazio → atualmente `isDemo=false`. Deveria ser distinguível.
- Definir o comportamento esperado e testar.

---

## Prioridade dos test gaps

| Gap | Prioridade | Prevenção de qual finding |
|---|---|---|
| 1. Contract tests | Imediata | Todos os C1–C3, A1–A4 |
| 4. Kill switch E2E | Antes de beta | C3, A3 |
| 5. Proxy auth gate | Imediata | C4 |
| 2. Models render vazio | Antes de beta | C1, M3 |
| 3. setBehavior unit | Antes de beta | C2 |
| 7. aion_mode fallbacks | Próximo sprint | regressão futura |
| 6. Mock coherence | Próximo sprint | regressão futura |
| 8. useApiData states | Próximo sprint | M3 |
