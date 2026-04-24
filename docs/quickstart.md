# AION Quickstart — Integration in Under 45 Minutes

AION is an OpenAI-compatible proxy. You change one line in your existing code.

---

## Prerequisites

- Docker or Python 3.11+
- An OpenAI-compatible API key (OpenAI, Azure, Anthropic, Ollama, etc.)
- Redis (optional — required for multi-turn context, session audit, budget cap)

---

## Step 1 — Run AION

**Docker (recommended)**

```bash
docker run -d \
  --name aion \
  -p 8000:8000 \
  -e OPENAI_API_KEY=sk-your-key \
  -e REDIS_URL=redis://your-redis:6379 \
  -e AION_MULTI_TURN_CONTEXT=true \
  -e AION_BUDGET_ENABLED=true \
  -e AION_SESSION_AUDIT_SECRET=change-me-to-a-real-secret \
  ghcr.io/your-org/aion:latest
```

**Python (pip)**

```bash
pip install aion-gateway
OPENAI_API_KEY=sk-your-key \
REDIS_URL=redis://localhost:6379 \
aion serve --port 8000
```

Verify it's up:

```bash
curl http://localhost:8000/health
# → {"status": "ok", "mode": "normal"}
```

---

## Step 2 — Point Your App at AION

Change `base_url` from OpenAI to AION. Nothing else changes.

**Python (openai SDK)**

```python
from openai import OpenAI

client = OpenAI(
    api_key="your-openai-key",
    base_url="http://localhost:8000/v1",  # ← only change
)
```

**JavaScript/TypeScript**

```typescript
const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
  baseURL: "http://localhost:8000/v1",  // ← only change
});
```

**curl**

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: your-tenant" \
  -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hello"}]}'
```

> **Multi-tenant:** Pass `X-Tenant-ID: <tenant>` header to isolate data, budgets, and audit trails per team/product.

---

## Step 3 — Configure Budget Cap (optional but recommended)

```bash
curl -X PUT http://localhost:8000/v1/budget/your-tenant \
  -H "Authorization: Bearer your-admin-key" \
  -H "Content-Type: application/json" \
  -d '{
    "daily_cap": 5.00,
    "on_cap_reached": "downgrade",
    "fallback_model": "gpt-4o-mini",
    "alert_threshold": 0.80,
    "alert_webhook_url": "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
  }'
```

Check status:

```bash
curl http://localhost:8000/v1/budget/your-tenant/status \
  -H "Authorization: Bearer your-admin-key"
```

---

## Step 4 — Verify AION Is Working

```bash
curl http://localhost:8000/v1/intelligence/your-tenant/overview
```

Expected response after a few requests:

```json
{
  "tenant": "your-tenant",
  "security": {"requests_blocked": 0, "pii_intercepted": 0},
  "economics": {"savings_usd": 0.0012, "savings_pct": 8.3},
  "intelligence": {"requests_processed": 4, "bypass_rate": 0.0, "avg_latency_ms": 94.0},
  "budget": {"daily_cap": 5.0, "today_spend": 0.0021, "cap_pct": 0.0}
}
```

---

## Step 5 — Enable Multi-Turn Session ID (recommended for production)

Pass a stable session ID per conversation so AION can track context across turns:

```python
client.chat.completions.create(
    model="gpt-4o-mini",
    messages=history,
    extra_headers={"X-Aion-Session-Id": f"user-{user_id}-conv-{conv_id}"},
)
```

Without this header, AION derives a session ID from the first message — works, but two users with identical first messages share context.

---

## Environment Variables Reference

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `OPENAI_API_KEY` | Yes | — | Forwarded to LLM provider |
| `REDIS_URL` | No | — | Enables session context, audit, budget |
| `AION_MULTI_TURN_CONTEXT` | No | `false` | Rolling 3-turn context window |
| `AION_BUDGET_ENABLED` | No | `false` | Budget cap enforcement |
| `AION_SESSION_AUDIT_SECRET` | No | — | HMAC key for audit trail signatures |
| `AION_FAIL_MODE` | No | `open` | `open` = degrade gracefully; `closed` = block on failure |
| `AION_SAFE_MODE` | No | `false` | Pure passthrough — disables all modules |
| `AION_ADMIN_KEY` | No | — | Format: `key1:admin,key2:operator` |

---

## Troubleshooting

**AION is blocking requests unexpectedly**
→ Check `/v1/explain/<request_id>` for the block reason.
→ Temporarily enable safe mode: `PUT /v1/killswitch {"active": true}` (requires admin key).

**Redis unavailable**
→ AION degrades gracefully: pipeline continues stateless, session audit and budget cap are disabled.
→ Check `/health` — mode will show `normal` even without Redis.

**High latency**
→ Pipeline overhead target is < 20ms P95. Check `X-Aion-Pipeline-Ms` header on each response.
→ Run `/v1/benchmark/<tenant>` for per-module latency breakdown.

**Need support**
→ Check `/v1/pipeline` for module status.
→ POST a reproduction to your AION admin with the `X-Request-ID` header from the failing response.
