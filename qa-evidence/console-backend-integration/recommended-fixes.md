# Fixes recomendados — Console ↔ Backend

Para cada CRÍTICO e ALTO, aqui está a abordagem mais barata que resolve sem refatorar arquitetura.

---

## Fix para [C1] — `/v1/models` retornar shape compatível com `ModelInfo`

**Prioridade:** Imediata
**Esforço estimado:** 4–6h (backend) + 1h (frontend)
**Abordagem:**

### Lado backend (preferido — fonte da verdade)
Em `aion/routers/observability.py:371-374`, expandir o handler para retornar todos os modelos configurados com o schema completo:

```python
@router.get("/v1/models", tags=["Observability"])
async def list_models():
    settings = get_settings()
    catalog = settings.model_catalog or [
        # Fallback: ao menos o default
        {"id": settings.default_model, "provider": settings.default_provider, "type": "default"},
    ]
    return {
        "models": [
            {
                "id": m["id"],
                "name": m.get("name", m["id"]),
                "provider": m["provider"],
                "cost_input_per_1m": m.get("cost_input_per_1m", 0),
                "cost_output_per_1m": m.get("cost_output_per_1m", 0),
                "max_tokens": m.get("max_tokens", 0),
                "latency_ms": m.get("latency_ms", 0),
                "capabilities": m.get("capabilities", []),
                "status": m.get("status", "active"),
            }
            for m in catalog
        ]
    }
```

`settings.model_catalog` precisa ser introduzido em `aion/config.py`. Pode vir de YAML (`config/models.yml`) ou env var `AION_MODELS_JSON`. Em prod, é onde ficam os 4–8 modelos configurados (gpt-4o, gpt-4o-mini, claude-sonnet, gemini-flash etc.).

### Lado frontend (fallback se backend não puder mudar agora)
Suavizar o type guard em `aion-console/src/lib/api/behavior.ts:31-41`:

```ts
function isModelInfoLike(x: unknown): x is ModelInfo {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return typeof o.id === "string" && o.id.length > 0 && typeof o.provider === "string";
}
```

E em `aion-console/src/lib/types.ts:43-53`, marcar campos opcionais:
```ts
export interface ModelInfo {
  id: string;
  provider: string;
  name?: string;
  cost_input_per_1m?: number;
  cost_output_per_1m?: number;
  max_tokens?: number;
  latency_ms?: number;
  capabilities?: string[];
  status?: "active" | "inactive" | "fallback";
}
```

E em `routing-page.tsx:345`:
```tsx
{(model.capabilities ?? []).map((cap) => ...)}
```

**Recomendação:** **fazer os dois lados.** Backend reporta a verdade, frontend é tolerante.

---

## Fix para [C2] — `setBehavior` zera os dials silenciosamente

**Prioridade:** Imediata
**Esforço estimado:** 2h
**Abordagem:**

### Decisão de produto necessária
O conceito de "Prioridade Economia ↔ Qualidade" no `/routing` precisa mapear para QUAL campo do `BehaviorConfig` do backend? As opções:
- `cost_target` (string `free|low|medium|high`) — mapping óbvio mas perde granularidade
- Adicionar campo `economy: int` (0-100) ao `BehaviorConfig` — preserva granularidade, requer migração de schema

### Implementação (assumindo opção 2)

**Backend** — adicionar `economy` ao `BehaviorConfig` em `aion/metis/behavior.py:27`:
```python
class BehaviorConfig(BaseModel):
    """Behavior dial settings."""
    model_config = ConfigDict(extra="forbid")  # ← critical: rejeitar campos extras
    objectivity: int = Field(default=50, ge=0, le=100)
    density: int = Field(default=50, ge=0, le=100)
    explanation: int = Field(default=50, ge=0, le=100)
    cost_target: str = Field(default="medium")
    formality: int = Field(default=50, ge=0, le=100)
    economy: int = Field(default=50, ge=0, le=100)  # NEW
```

**Frontend** — em `routing-page.tsx:102`, agora o `setBehavior({economy: priority})` funciona como esperado.

**Bonus:** com `extra="forbid"`, qualquer mismatch futuro retorna 422 para o frontend ao invés de silêncio. O `useApiData` mostra demo banner.

### Alternativa rápida (sem migração)
Se não puder adicionar campo agora, em `routing-page.tsx:102` mapear o slider para `cost_target`:
```tsx
const costTarget = priority < 25 ? "free" : priority < 50 ? "low" : priority < 75 ? "medium" : "high";
await setBehavior({ cost_target: costTarget });
```
Mas a decisão de produto precisa documentar essa perda de granularidade.

---

## Fix para [C3] — `/v1/killswitch` GET retorna `{safe_mode}`, frontend espera `{killswitch_active}`

**Prioridade:** Imediata
**Esforço estimado:** 1–2h
**Abordagem:**

### Lado backend (preferido — frontend já está usando esse contrato em outros lugares)
Em `aion/routers/control_plane.py:49-55`, normalizar o nome do campo:

```python
@router.get("/v1/killswitch", tags=["Control Plane"])
async def get_killswitch():
    _pipeline = _get_pipeline()
    if not _pipeline:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    settings = get_settings()
    return {
        "killswitch_active": settings.safe_mode,
        "reason": getattr(_pipeline, "_safe_mode_reason", None),
        "expires_at": getattr(_pipeline, "_safe_mode_expires_at", None),
    }
```

E em `:25-37` (PUT) — devolver o mesmo shape:
```python
@router.put("/v1/killswitch", tags=["Control Plane"])
async def activate_killswitch(request: Request):
    ...
    body = await request.json()
    reason = body.get("reason", "manual")
    duration = body.get("duration_seconds")  # NEW: respeitar TTL do frontend
    expires_at = int(time.time() + duration) if duration else None
    _pipeline.activate_safe_mode(reason, expires_at=expires_at)  # backend precisa aceitar
    return {
        "killswitch_active": True,
        "reason": reason,
        "expires_at": expires_at,
    }
```

`pipeline.activate_safe_mode` precisa armazenar `_safe_mode_reason` e `_safe_mode_expires_at`. Hoje só armazena `safe_mode = True`.

E em `:40-46` (DELETE):
```python
return {"killswitch_active": False}
```

### Lado frontend (fallback temporário)
Se o backend não puder mudar agora, em `aion-console/src/lib/api/protection.ts:67-72` fazer um adapter:

```ts
export async function getKillswitch(): Promise<{
  killswitch_active: boolean;
  reason?: string;
  expires_at?: number;
}> {
  const raw = await fetchApi<{safe_mode?: boolean; killswitch_active?: boolean; reason?: string; expires_at?: number}>("/v1/killswitch");
  return {
    killswitch_active: raw.killswitch_active ?? raw.safe_mode ?? false,
    reason: raw.reason,
    expires_at: raw.expires_at,
  };
}
```

**Recomendação:** corrigir backend. O frontend está mais consistente com o conceito ("killswitch ativo" é mais semântico que "safe_mode" no contexto da UI).

---

## Fix para [C4] — Proxy não bloqueia requests não autenticados

**Prioridade:** Imediata (assumindo que o middleware do Next.js NÃO está protegendo `/api/proxy/*`)
**Esforço estimado:** 30 min
**Abordagem:**

### Verificar primeiro
Antes de mudar código, verificar se existe `aion-console/src/middleware.ts` ou `aion-console/middleware.ts` que protege `/api/proxy/*`. Se sim, validar o `matcher` config.

```bash
# A partir de aion-console/
grep -rE "matcher|api/proxy" src/middleware.ts middleware.ts 2>/dev/null
```

Se o middleware NÃO cobre `/api/proxy/*`, é vulnerabilidade.

### Fix dentro do route handler
Em `aion-console/src/app/api/proxy/[...path]/route.ts:62`, adicionar early return:

```ts
const session = await auth();
if (!session?.user) {
  return new Response(JSON.stringify({ error: "Unauthorized" }), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  });
}

// Daqui pra baixo é o código atual
forwardedHeaders["X-Aion-Actor-Id"] = session.user.email!;
forwardedHeaders["X-Aion-Actor-Role"] = session.user.role ?? "viewer";
forwardedHeaders["X-Aion-Auth-Source"] = session.user.provider ?? "unknown";
```

### Fix complementar: middleware (preferido)
Adicionar/atualizar `aion-console/src/middleware.ts`:

```ts
import { auth } from "@/auth";
import { NextResponse } from "next/server";

export default auth((req) => {
  const isPublic = req.nextUrl.pathname.startsWith("/login") ||
                   req.nextUrl.pathname.startsWith("/api/auth");
  if (!isPublic && !req.auth) {
    return NextResponse.redirect(new URL("/login", req.url));
  }
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|public).*)"],
};
```

---

## Fix para [A1] — `getBehavior()` desempacotar envelope

**Prioridade:** Antes de beta
**Esforço estimado:** 15 min
**Abordagem:**

Em `aion-console/src/lib/api/behavior.ts:6-8`:
```ts
export async function getBehavior(): Promise<BehaviorDial> {
  const raw = await fetchApi<{tenant: string; behavior: BehaviorDial | null}>("/v1/behavior");
  if (raw.behavior === null) {
    // Backend has no config saved — return defaults
    return { objectivity: 50, density: 50, explanation: 50, cost_target: "medium", formality: 50 } as unknown as BehaviorDial;
  }
  return raw.behavior;
}
```

(Ajustar para o shape correto após corrigir A2.)

---

## Fix para [A2] — Sincronizar `BehaviorDial` com `BehaviorConfig`

**Prioridade:** Antes de beta
**Esforço estimado:** 2h (decisão de produto + implementação)
**Abordagem:** Decidir conjunto canônico de fields. Recomendação: usar o backend como fonte da verdade — adotar `density, objectivity, explanation, cost_target, formality` no frontend e remover os campos não suportados (`verbosity, confidence, safe_mode`) ou implementá-los no backend conforme decisão de produto.

Tipo final em `aion-console/src/lib/types.ts:33-41`:
```ts
export interface BehaviorDial {
  objectivity: number;       // 0-100
  density: number;           // 0-100  (era "verbosity")
  explanation: number;       // 0-100
  cost_target: "free" | "low" | "medium" | "high";  // era "economy"
  formality: number;         // 0-100
  // confidence, safe_mode: removidos (não modelados no backend)
}
```

E ajustar todos os componentes que liam os campos removidos.

---

## Fix para [A3] — `PUT /v1/killswitch` retornar shape completo + suportar TTL

Já incluído no fix de C3 acima.

---

## Fix para [A4] — Backend `/v1/models` expor todos os campos de `ModelInfo`

Já incluído no fix de C1 acima.

---

## Sumário de prioridades

| Severidade | Fix | Quando |
|---|---|---|
| C1 | Expandir `/v1/models` schema | Imediata — antes de qualquer demo de routing |
| C2 | `extra="forbid"` + sync de campo (`economy` ou `cost_target`) | Imediata — toda interação com slider corrompe estado hoje |
| C3 | Renomear `safe_mode → killswitch_active` no backend | Imediata — kill switch é feature de incidente |
| C4 | Adicionar `if (!session) return 401` no proxy + middleware | Imediata — pode ser vetor de bypass |
| A1 | `getBehavior()` desempacotar envelope | Antes de beta |
| A2 | Sincronizar tipos `BehaviorDial ↔ BehaviorConfig` | Antes de beta |
| A3 | KS PUT retornar `{killswitch_active, reason, expires_at}` + TTL | Antes de beta |
| A4 | Backend `/v1/models` retornar todos os campos | Antes de beta |
| M1 | Remover dead code `getTenantSettings`/`updateTenantSettings` | Próximo sprint |
| M2 | Adicionar `extra="forbid"` em todos os Pydantic models de write | Próximo sprint |
| M3 | `useApiData` detectar "sucesso mas array vazio inesperado" | Próximo sprint |

**Total estimado para sair do "POC":** 12–18 horas de dev (backend + frontend) + 4 horas de teste.
