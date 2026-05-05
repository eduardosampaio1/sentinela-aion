# Fixes recomendados V2 — para sair de "APTO COM RESTRIÇÕES" para "APTO PARA PRODUÇÃO"

Quatro fixes para os ALTOs (N1, N2, N6) + um MÉDIO (N5). Estimativa total: 8–12 horas.

---

## Fix para [N1+N2] — Catálogo de modelos vir do tenant config + status real do circuit breaker

**Prioridade:** Antes de beta
**Esforço estimado:** 4–6h

**Abordagem:**

### Passo 1 — Definir fonte do catálogo
Opção A (recomendada): usar `config/models.yaml` como source of truth.

Criar `D:\projetos\sentinela-aion-main\config\models.yaml`:
```yaml
models:
  - id: gpt-4o-mini
    name: GPT-4o Mini
    provider: openai
    cost_input_per_1m: 0.15
    cost_output_per_1m: 0.60
    max_tokens: 128000
    latency_ms: 890
    capabilities: [chat, tools, json, vision]
  # ... outros
```

### Passo 2 — Carregar e cruzar com circuit breaker
Em `aion/routers/observability.py:371`:

```python
import yaml
from pathlib import Path
from aion.proxy import get_circuit_breaker_status  # já existe

@router.get("/v1/models")
async def list_models():
    settings = get_settings()
    models_yaml = Path(settings.config_dir) / "models.yaml"
    if not models_yaml.exists():
        # Fallback: só o default_model configurado
        return {"models": [{
            "id": settings.default_model,
            "provider": settings.default_provider,
            "status": "active",
        }]}

    with models_yaml.open() as f:
        catalog = yaml.safe_load(f)["models"]

    # Cruza com credenciais configuradas
    has_credentials = {
        "openai": bool(getattr(settings, "openai_api_key", None)),
        "anthropic": bool(getattr(settings, "anthropic_api_key", None)),
        "google": bool(getattr(settings, "google_api_key", None)),
    }

    # Cruza com circuit breaker (OPEN = error, HALF_OPEN = degraded)
    cb_status = get_circuit_breaker_status()  # {"openai": "closed", "anthropic": "open", ...}

    for m in catalog:
        provider = m["provider"]
        if not has_credentials.get(provider, False):
            m["status"] = "inactive"  # NOVO valor — sem credenciais
        elif cb_status.get(provider) == "open":
            m["status"] = "error"      # frontend já trata como "Indisponível"
        elif cb_status.get(provider) == "half_open":
            m["status"] = "fallback"
        else:
            m["status"] = "active"

    return {"models": catalog}
```

### Passo 3 — Frontend: tratar `inactive`
Em `aion-console/src/lib/types.ts:53`:
```ts
status?: "active" | "inactive" | "fallback" | "error";
```

E em `routing-page.tsx`, o `statusBadge` já tem case para "inactive". Adicionar case para "error".

---

## Fix para [N6] — Auth gate fail-closed por padrão

**Prioridade:** Imediata
**Esforço estimado:** 30 min

**Abordagem:**

Em `aion-console/src/app/api/proxy/[...path]/route.ts:65-75`, inverter a lógica:

```ts
const session = await auth();
if (!session?.user) {
  // Fail-closed por padrão. Bypass APENAS via opt-in explícito,
  // que ninguém vai setar acidentalmente em produção.
  const allowDevBypass =
    process.env.NODE_ENV !== "production" &&
    process.env.AION_PROXY_DEV_BYPASS === "true";

  if (!allowDevBypass) {
    return new Response(
      JSON.stringify({ error: "Unauthorized", reason: "no_session" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    );
  }
  console.warn("[proxy] DEV BYPASS active — request reached backend without session");
}
```

**Documentar em `.env.example`:**
```
# Local dev only — bypass the proxy auth gate when running without OAuth setup.
# NEVER set in production. Any non-dev value is ignored.
AION_PROXY_DEV_BYPASS=false
```

---

## Fix para [N5] — Persistir killswitch em Redis

**Prioridade:** Antes de beta
**Esforço estimado:** 2–3h

**Abordagem:**

Em `aion/pipeline.py`, adicionar load/save em Redis:

```python
import asyncio

class Pipeline:
    _REDIS_KEY = "aion:pipeline:safe_mode"

    async def restore_safe_mode_from_redis(self) -> None:
        """Called once at startup to restore killswitch state from Redis."""
        try:
            from aion.metis.behavior import _get_redis
            r = await _get_redis()
            if not r:
                return
            data = await r.get(self._REDIS_KEY)
            if not data:
                return
            import json
            state = json.loads(data)
            expires_at = state.get("expires_at")
            # Check TTL hasn't elapsed during downtime
            if expires_at is not None and time.time() >= expires_at:
                await r.delete(self._REDIS_KEY)
                return
            self._safe_mode = True
            self._safe_mode_reason = state.get("reason", "")
            self._safe_mode_expires_at = expires_at
            logger.warning("Killswitch state restored from Redis: reason=%s", self._safe_mode_reason)
        except Exception as e:
            logger.warning("Failed to restore killswitch state from Redis: %s", e)

    def activate_safe_mode(self, reason: str = "manual", expires_at: Optional[float] = None) -> None:
        # ... existing logic ...
        # NEW: persist to Redis (fire-and-forget)
        asyncio.create_task(self._persist_safe_mode())

    async def _persist_safe_mode(self) -> None:
        try:
            from aion.metis.behavior import _get_redis
            r = await _get_redis()
            if not r:
                return
            import json
            payload = json.dumps({"reason": self._safe_mode_reason, "expires_at": self._safe_mode_expires_at})
            ttl = int(self._safe_mode_expires_at - time.time()) if self._safe_mode_expires_at else None
            if ttl is not None and ttl > 0:
                await r.setex(self._REDIS_KEY, ttl, payload)
            else:
                await r.set(self._REDIS_KEY, payload)
        except Exception:
            pass

    def deactivate_safe_mode(self) -> None:
        # ... existing logic ...
        asyncio.create_task(self._clear_safe_mode_redis())

    async def _clear_safe_mode_redis(self) -> None:
        try:
            from aion.metis.behavior import _get_redis
            r = await _get_redis()
            if r:
                await r.delete(self._REDIS_KEY)
        except Exception:
            pass
```

E em `aion/main.py`, no startup:
```python
await pipeline.restore_safe_mode_from_redis()
```

---

## Fix para [N3] — Property sem efeito colateral

**Prioridade:** Próximo sprint (estilo)
**Esforço estimado:** 30 min

Mover o auto-deactivate para `is_safe_mode()` (que já está fazendo) e tornar `safe_mode_state` puramente leitura:

```python
@property
def safe_mode_state(self) -> dict:
    """Pure read — no side effects. Use is_safe_mode() to trigger TTL check."""
    # Trigger any TTL-based deactivation first via the explicit method
    _ = self.is_safe_mode()  # has the side effect intentionally
    return {
        "killswitch_active": self._safe_mode,
        "reason": self._safe_mode_reason or None,
        "expires_at": self._safe_mode_expires_at,
    }
```

Ainda tem o efeito colateral na chamada acima (via `is_safe_mode`), mas fica claro pela leitura. Alternativa mais limpa: extrair `_check_ttl_expiry()` privado, chamado pelos dois.

---

## Fix para [N4] — Optimistic concurrency em setBehavior

**Prioridade:** Próximo sprint
**Esforço estimado:** 2h

Adicionar `If-Match` ETag header. Backend retorna `version: int` no GET, exige `If-Match: <version>` no PUT, retorna 412 Precondition Failed em conflito.

(Implementação detalhada omitida — padrão clássico HTTP.)

---

## Pendentes da auditoria anterior (M1, M2, M3)

### [M1] — Remover dead code

```bash
# Em aion-console/src/lib/api/admin.ts, remover:
# - getTenantSettings()
# - updateTenantSettings()
# E ajustar exports em index.ts
```

### [M2] — Padronizar `extra="forbid"` em todos os Pydantic body models

Hoje só `BehaviorConfig` tem. Criar `aion/shared/strict_model.py` com:
```python
from pydantic import BaseModel, ConfigDict
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

E migrar models existentes (poucos hoje, mas o padrão fica).

### [M3] — `useApiData` distinguir empty vs offline

Adicionar opção `treatEmptyAsDemo: (data: T) => boolean`:
```ts
useApiData(getModels, mockModels, {
  treatEmptyAsDemo: (data) => data.length === 0,  // empty array = backend disagrees
});
```

Quando o callback retorna true, dispara `isDemo=true` mesmo em fetch ok.

---

## Sumário de prioridades V2

| Severidade | Fix | Esforço | Prazo |
|---|---|---|---|
| ALTO | N6 — auth gate fail-closed | 30 min | Imediata |
| ALTO | N1+N2 — catálogo real + circuit breaker | 4–6h | Antes de beta |
| MÉDIO | N5 — killswitch persistido | 2–3h | Antes de beta |
| MÉDIO | M1 — dead code | 15 min | Próximo sprint |
| MÉDIO | M2 — `extra="forbid"` global | 1h | Próximo sprint |
| MÉDIO | M3 — useApiData empty detection | 1h | Próximo sprint |
| BAIXO | N3, N4, N7 | — | Backlog |

**Total para virar "APTO PARA PRODUÇÃO":** 7–10h dev + 2h teste.
