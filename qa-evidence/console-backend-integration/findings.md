# Findings — Console ↔ Backend

Findings ordenados por severidade. Todos os caminhos são relativos ao monorepo `D:\projetos\sentinela-aion-main\`.

---

## 🔴 CRÍTICOS

### [C1] — `/v1/models` retorna apenas 1 modelo, frontend exige array de modelos com schema rico

**Componente:** `aion/routers/observability.py` ↔ `aion-console/src/lib/api/behavior.ts` ↔ `aion-console/src/components/routing/routing-page.tsx`

**Arquivos:**
- Backend: `aion/routers/observability.py:371-374`
  ```python
  @router.get("/v1/models", tags=["Observability"])
  async def list_models():
      settings = get_settings()
      return {"models": [{"id": settings.default_model, "provider": settings.default_provider, "type": "default"}]}
  ```
- Frontend type: `aion-console/src/lib/types.ts:43-53` — exige `cost_input_per_1m`, `cost_output_per_1m`, `max_tokens`, `latency_ms`, `capabilities[]`, `status`
- Frontend type guard: `aion-console/src/lib/api/behavior.ts:31-41` — REQUER `capabilities` ser array de strings
- Consumidor: `aion-console/src/components/routing/routing-page.tsx:46, 345` — chama `model.capabilities.map(...)` e usa `cost_output_per_1m`

**Risco:** A página `/routing` (Roteamento) mostra **grid vazio de modelos** sem qualquer aviso ao usuário.

**Condição de disparo:** Sempre que o usuário abre `/routing`. O backend retorna 200 com 1 modelo, o frontend filtra-o no type guard (porque falta `capabilities`), `useApiData` recebe `[]` SEM erro → não dispara o demo banner. Tela fica visualmente como "nenhum modelo configurado".

**Impacto:** Cliente em demo conclui que o produto "não tem modelos configurados" mesmo que o backend tenha o `default_model` setado corretamente. Em ambiente de produção real, mesmo problema — só veria modelos se o backend listasse os `additional_models` do config (que ele NÃO faz).

---

### [C2] — `setBehavior({economy: N})` zera silenciosamente todos os dials para default

**Componente:** `aion-console/src/components/routing/routing-page.tsx` ↔ `aion/routers/control_plane.py` ↔ `aion/metis/behavior.py`

**Arquivos:**
- Frontend: `aion-console/src/components/routing/routing-page.tsx:102`
  ```tsx
  await setBehavior({ economy: priority });
  ```
- Frontend type: `aion-console/src/lib/types.ts:33-41` — `BehaviorDial { objectivity, verbosity, economy, explanation, confidence, safe_mode, formality }`
- Backend type: `aion/metis/behavior.py:27-34` — `BehaviorConfig { objectivity, density, explanation, cost_target: str, formality }`
- Backend handler: `aion/routers/control_plane.py:126-135`
  ```python
  body = await request.json()
  config = BehaviorConfig(**body)  # Pydantic v2 default: extra="ignore"
  await dial.set(config, tenant)
  ```

**Risco:** Pydantic v2 ignora silenciosamente `economy` (campo inexistente no modelo). Como nenhum outro campo foi enviado, o `BehaviorConfig` é instanciado com TODOS os defaults: `objectivity=50, density=50, explanation=50, cost_target="medium", formality=50`. **Esses defaults são então persistidos no Redis sobrescrevendo qualquer config anterior.**

**Condição de disparo:** Toda vez que o usuário move o slider "Prioridade Economia ↔ Qualidade" e clica "Salvar prioridade" em `/routing`. O backend retorna 200 com a config defaultada — o frontend mostra success mas o efeito é o oposto do desejado.

**Impacto:** Configuração de comportamento do Metis fica ZERADA depois de qualquer interação com esse slider. Operador pensa que ajustou para `economy=80` (favor economy) e na verdade ajustou para `density=50, formality=50, cost_target="medium"` (todos médios, sem prioridade alguma).

---

### [C3] — `GET /v1/killswitch` retorna `{safe_mode}` mas frontend lê `killswitch_active`

**Componente:** `aion/routers/control_plane.py` ↔ `aion-console/src/lib/api/protection.ts` ↔ Settings page (nova aba "Controles avançados")

**Arquivos:**
- Backend: `aion/routers/control_plane.py:49-55`
  ```python
  @router.get("/v1/killswitch", tags=["Control Plane"])
  async def get_killswitch():
      ...
      return {"safe_mode": settings.safe_mode}
  ```
- Frontend: `aion-console/src/lib/api/protection.ts:67-72`
  ```ts
  export async function getKillswitch(): Promise<{
    killswitch_active: boolean;
    reason?: string;
    expires_at?: number;
  }>
  ```
- Consumidores:
  - `aion-console/src/components/settings/settings-page.tsx:114-120` (aba "Controles avançados", recém-criada)
  - `aion-console/src/components/estixe/estixe-page.tsx:117-124` (banner de KS ativo no topo)

**Risco:** `setKsActive(res.killswitch_active)` recebe `undefined` (não existe no payload). React trata como falsy. **A UI mostra "Kill Switch INATIVO" mesmo quando o backend está em safe_mode.**

**Condição de disparo:** Sempre que a página `/settings → Controles avançados` ou `/estixe` carrega, o componente faz `getKillswitch()` e o estado é populado errado.

**Impacto:** Operador não vê que o sistema está parado pelo console. Vai para outras telas, vê dados aparentemente normais (mas backend está rejeitando todo tráfego), e demora para entender que precisa desativar o kill switch. Em incidente real, isso atrasa a recuperação.

**Bug correlacionado:** `PUT /v1/killswitch` retorna `{status: "safe_mode_active", reason}` — também sem `expires_at` nem `killswitch_active`. Frontend faz `setKsExpires(res.expires_at)` → undefined. Banner do KS ativo não mostra horário de expiração. **Ainda pior: o `duration_seconds` enviado pelo frontend é silenciosamente ignorado pelo backend** (não existe TTL no killswitch atual).

---

### [C4] — Proxy `/api/proxy/[...path]/route.ts` não bloqueia requests não autenticados

**Componente:** `aion-console/src/app/api/proxy/[...path]/route.ts`

**Arquivo:** `aion-console/src/app/api/proxy/[...path]/route.ts:62-73`
```ts
const session = await auth();
if (session?.user) {
  if (session.user.email) forwardedHeaders["X-Aion-Actor-Id"] = session.user.email;
  if (session.user.role) forwardedHeaders["X-Aion-Actor-Role"] = session.user.role;
  if (session.user.provider) forwardedHeaders["X-Aion-Auth-Source"] = session.user.provider;
}
```

**Risco:** Se `session === null` (usuário não autenticado), a função NÃO retorna 401. Continua o fluxo normal e injeta a `AION_API_KEY` server-side (linha 56-58: `if (API_KEY) { Authorization: Bearer ... }`). Resultado: **chamada sem auth chega ao backend com Authorization: Bearer <admin-key>**.

**Condição de disparo:** Qualquer cliente HTTP (cURL, browser sem cookie, request inter-servidor) que conheça a URL pública `https://console.host/api/proxy/v1/<algo>` pode invocar endpoints administrativos.

**Mitigação parcial (não verificada nesta auditoria):** O Next.js middleware (`middleware.ts`, se existir) pode estar bloqueando rotas não autenticadas globalmente. **Precisa ser verificado.** Se não estiver, é vetor de bypass de auth completo — qualquer um pode ativar killswitch, deletar dados (LGPD), rotacionar chaves, etc.

**Impacto se confirmado:** acesso completo a operações destrutivas sem login.

---

## 🟠 ALTOS

### [A1] — `getBehavior()` tipa retorno como `BehaviorDial` mas backend retorna envelope `{tenant, behavior}`

**Componente:** `aion-console/src/lib/api/behavior.ts:6-8`
```ts
export async function getBehavior(): Promise<BehaviorDial> {
  return fetchApi("/v1/behavior");
}
```

**Backend:** `aion/routers/control_plane.py:114-123` retorna `{tenant: string, behavior: BehaviorConfig | null}`.

**Risco:** Quem chamar `getBehavior()` e ler `data.objectivity` direto vai receber `undefined`. Hoje **NINGUÉM chama `getBehavior()`** no código (verifiquei via grep) — é dead code. Mas vai quebrar quando alguém adicionar uma tela "Behavior dial".

**Severidade:** ALTO porque o tipo está mentindo. Refator futuro vai herdar o bug.

---

### [A2] — `BehaviorDial` (frontend) e `BehaviorConfig` (backend) têm campos quase disjuntos

**Frontend** (`aion-console/src/lib/types.ts:33-41`): `objectivity, verbosity, economy, explanation, confidence, safe_mode, formality`
**Backend** (`aion/metis/behavior.py:27-34`): `objectivity, density, explanation, cost_target, formality`

**Match:** apenas `objectivity, explanation, formality` (3 campos)
**Frontend-only:** `verbosity, economy, confidence, safe_mode` (4 campos)
**Backend-only:** `density, cost_target` (2 campos)

**Risco:** Mesmo que C2 seja corrigido, a sincronização de tipos está errada. Frontend assume conceitos (`economy`, `verbosity`, `confidence`, `safe_mode`) que o backend não modela. Backend tem conceitos (`density`, `cost_target`) que o frontend ignora.

---

### [A3] — `/v1/killswitch` PUT response shape difere do que `activateKillswitch()` espera

**Backend:** `aion/routers/control_plane.py:25-37`
```python
return {"status": "safe_mode_active", "reason": reason}
```

**Frontend:** `aion-console/src/lib/api/protection.ts:75-85`
```ts
export async function activateKillswitch(...): Promise<{
  killswitch_active: true;
  reason: string;
  expires_at: number;
}>
```

**Risco:** Resposta tem só `status` + `reason`. Falta `killswitch_active`, `expires_at`. Frontend depois lê `res.expires_at` → undefined → banner de KS ativo no `/estixe` não mostra horário de expiração.

**Bonus:** o body envia `duration_seconds: 3600` que é silenciosamente descartado — o backend nem suporta TTL hoje. Isso é uma **feature missing**, não só wiring.

---

### [A4] — Frontend `ModelInfo` exige campos que o backend nunca expõe

`aion-console/src/lib/types.ts:43-53`:
```ts
export interface ModelInfo {
  id: string;
  provider: string;
  name: string;            // ← backend não retorna
  cost_input_per_1m: number;   // ← backend não retorna
  cost_output_per_1m: number;  // ← backend não retorna
  max_tokens: number;          // ← backend não retorna
  latency_ms: number;          // ← backend não retorna
  capabilities: string[];      // ← backend não retorna
  status: "active" | "inactive" | "fallback";  // ← backend não retorna
}
```

Backend retorna apenas `{id, provider, type}`. Mesmo se C1 for corrigido (retornar TODOS os modelos), os outros 7 campos continuariam faltando. **Toda a tela de "Distribuição de modelos" e "Provedores" em `/routing` é alimentada por mock hoje**, não por dados reais.

---

## 🟡 MÉDIOS

### [M1] — Dead code: `getTenantSettings` e `updateTenantSettings`

**Componente:** `aion-console/src/lib/api/admin.ts:64-75`

Funções `getTenantSettings()` e `updateTenantSettings()` exportadas pelo barrel `lib/api/index.ts`. O backend NÃO tem rota `/v1/tenant/{tenant}/settings` (verificado via grep). Mas TAMBÉM **nenhum componente chama essas funções** (verificado via grep em `src/components`).

**Impacto:** dead code. Pequeno tamanho, mas confunde mantenedores futuros e finge feature que não existe.

---

### [M2] — Pydantic `BehaviorConfig` não usa `extra="forbid"` — falhas viram silêncio

`aion/metis/behavior.py:27-34`: BaseModel sem `model_config = ConfigDict(extra="forbid")`.

**Impacto:** todos os bugs de "frontend manda campo errado" são engolidos. Aumenta drasticamente a chance de defeitos como C2 passarem despercebidos.

---

### [M3] — `useApiData` não distingue "API ok mas vazia" de "API ok com dados"

`aion-console/src/lib/use-api-data.ts:52-67`: o `isDemo` só é `true` em catch. Quando `getModels()` retorna `[]` por causa do type guard filtrando tudo, o hook acha que foi sucesso. **Demo banner não dispara mesmo quando 100% dos dados foram filtrados.**

**Impacto:** mesma cara entre "backend offline" e "backend online com schema errado". O usuário não tem como distinguir.

---

## 🟢 BAIXOS

### [B1] — Endpoints de cliente (não-console) não usados pelo frontend — intencional

Backend expõe `/v1/decide`, `/v1/chat/completions`, `/v1/chat/assisted`, `/v1/decisions`. **Esses são para a APLICAÇÃO CLIENTE chamar AION**, não para o console. Não é bug.

### [B2] — Endpoints backend sem consumidor no console (gap de feature, não bug)

- `GET /v1/session/{id}/audit/export` — feature de exportação não exposta no console
- `POST/GET/DELETE /v1/collective/packs` — gestão de packs não exposta
- `GET /v1/approvals/{id}` (single) — só lista é usada
- `GET /metrics`, `/ready`, `/version`, `/v1/metrics/tenant/{tenant}` — endpoints de infra
