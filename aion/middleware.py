"""AION Middleware — central security, validation, rate limiting, and audit layer.

Async-first. Redis-backed when available (cluster-safe). Local fallback.
Follows the same pattern as aion/metis/behavior.py.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import OrderedDict, deque
from typing import Any, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from aion.config import get_settings
from aion.shared.contracts import Role, check_permission

logger = logging.getLogger("aion.middleware")

# ── Tenant validation ──
_TENANT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# ── Admin paths ──
_ADMIN_EXACT = {"/v1/killswitch", "/v1/behavior", "/v1/overrides", "/v1/audit", "/v1/approvals"}
_ADMIN_PREFIXES = ("/v1/estixe/", "/v1/modules/", "/v1/data/", "/v1/audit/", "/v1/calibration/", "/v1/budget/", "/v1/threats/", "/v1/reports/", "/v1/admin/", "/v1/approvals/")

# ── Roles whose service key is trusted to forward actor identity headers ──
# Only these roles can set X-Aion-Actor-* headers that drive RBAC.
# Any other caller's actor headers are ignored for authorization purposes.
_TRUSTED_PROXY_ROLES: frozenset[str] = frozenset({"console_proxy"})

# ── Endpoints that require X-Aion-Actor-Reason header ──
# Dangerous mutations must include a human-readable justification for the audit trail.
_REASON_REQUIRED: list[tuple[str, str]] = [
    ("PUT", "/v1/killswitch"),
    ("DELETE", "/v1/killswitch"),
    ("POST", "/v1/calibration/"),   # promote and rollback
    ("PUT", "/v1/modules/"),        # module toggle
    ("PUT", "/v1/budget/"),         # budget cap change
    ("POST", "/v1/approvals/"),     # approval resolution
    ("DELETE", "/v1/data/"),        # LGPD deletion
    ("POST", "/v1/admin/"),         # key rotation and admin ops
    ("DELETE", "/v1/overrides"),    # override removal
]

# ── RBAC: map (method, path_prefix) → required permission ──
_PATH_PERMISSIONS: list[tuple[str, str, str]] = [
    # (method, path_startswith, permission)
    ("PUT", "/v1/killswitch", "killswitch:write"),
    ("DELETE", "/v1/killswitch", "killswitch:write"),
    ("GET", "/v1/killswitch", "killswitch:read"),
    ("PUT", "/v1/overrides", "overrides:write"),
    ("DELETE", "/v1/overrides", "overrides:write"),
    ("GET", "/v1/overrides", "overrides:read"),
    ("PUT", "/v1/behavior", "behavior:write"),
    ("DELETE", "/v1/behavior", "behavior:write"),
    ("GET", "/v1/behavior", "behavior:read"),
    ("PUT", "/v1/modules/", "modules:write"),
    ("GET", "/v1/modules/", "modules:read"),
    ("POST", "/v1/estixe/", "estixe:reload"),
    ("DELETE", "/v1/data/", "data:delete"),
    ("GET", "/v1/audit", "audit:read"),
    # Calibration (shadow mode) — promote/rollback have dedicated permissions (resolved by path suffix)
    ("GET", "/v1/calibration/", "overrides:read"),
    ("POST", "/v1/calibration/", "calibration:promote"),  # fallback; path suffix overrides below
    # Budget cap
    ("PUT", "/v1/budget/", "budget:write"),
    ("GET", "/v1/budget/", "budget:read"),
    # Threat signals
    ("GET", "/v1/threats/", "audit:read"),
    # Executive reports
    ("GET", "/v1/reports/", "audit:read"),
    ("POST", "/v1/reports/", "budget:write"),
    ("DELETE", "/v1/reports/", "budget:write"),
    # Approvals
    ("POST", "/v1/approvals/", "approvals:resolve"),
    ("GET", "/v1/approvals", "audit:read"),
    # Admin operations (key rotation) — admin only
    ("POST", "/v1/admin/", "keys:rotate"),
    # AION Collective editorial exchange
    ("GET",  "/v1/collective/", "collective:read"),
    ("POST", "/v1/collective/", "collective:install"),
    ("PUT",  "/v1/collective/", "collective:install"),
]

# ── Permissions that require auth even when AION_ADMIN_KEY is not configured ──
# Fail-secure: destructive operations block unless a key is explicitly set.
_CRITICAL_PERMISSIONS = {"killswitch:write", "data:delete"}

# ── API key → role mapping (loaded from config) ──
# Format in env: AION_ADMIN_KEY=key1:admin,key2:operator,key3:viewer
def _parse_key_roles(admin_key_str: str) -> dict[str, str]:
    """Parse 'key1:admin,key2:operator' into {key1: admin, key2: operator}.
    Keys without role default to 'admin' for backward compat."""
    result = {}
    for part in admin_key_str.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            key, role = part.rsplit(":", 1)
            result[key.strip()] = role.strip()
        else:
            result[part] = Role.ADMIN  # backward compat
    return result

# ── Limits (defaults, overridable via AionSettings) ──
_MAX_IN_FLIGHT = 500

# ── In-flight counter ──
_requests_in_flight = 0

# ── Redis client (async, lazy init) ──
_redis_client = None
_redis_available = False

# ── Local fallback store (always available) ──
_local_rate_limits: dict[str, list[float]] = {}
_local_audit_log: deque[dict] = deque(maxlen=10_000)
_local_overrides: dict[str, dict] = {}  # tenant → overrides


# ── File-based persistence fallback (when no Redis) ──
# Problema que isso resolve: _local_overrides e in-memory => restart zera configs.
# Em prod real, use Redis (REDIS_URL). Em sim/dev, persiste em JSON para sobreviver a restart.
def _overrides_file() -> "Path":
    from pathlib import Path
    import os
    # AION_RUNTIME_DIR: base para estado persistente local (default: cwd/.runtime)
    base = Path(os.environ.get("AION_RUNTIME_DIR", ".runtime"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "overrides.json"


def _persist_overrides_to_disk() -> None:
    """Serializa _local_overrides para disco. No-op se erro."""
    try:
        with open(_overrides_file(), "w", encoding="utf-8") as f:
            json.dump(_local_overrides, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("overrides persist to disk failed: %s", e)


def _load_overrides_from_disk() -> None:
    """Carrega _local_overrides do disco na inicializacao. Chamado 1x em lifespan."""
    global _local_overrides
    try:
        path = _overrides_file()
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                _local_overrides = json.load(f)
            logger.info(
                "Overrides carregados do disco: %d tenants (arquivo=%s)",
                len(_local_overrides), path,
            )
    except Exception as e:
        logger.warning("Falha ao carregar overrides do disco: %s", e)


# ════════════════════════════════════════════
# Redis client (async, lazy — same as behavior.py)
# ════════════════════════════════════════════

# Circuit breaker leve: quando Redis falha, marca disponibilidade=False por
# _redis_retry_interval segundos. Evita timeout em cada call quando Redis cai.
_redis_last_failure: float = 0.0
_redis_retry_interval: float = 10.0  # segundos entre retries quando down


async def _get_redis():
    """Get or create async Redis client. Returns None if unavailable.

    Circuit breaker: se Redis falhou recentemente (<10s), retorna None sem tentar.
    """
    global _redis_client, _redis_available, _redis_last_failure

    # Circuit breaker: se falhou recentemente, skip
    if _redis_last_failure > 0 and (time.time() - _redis_last_failure) < _redis_retry_interval:
        return None

    if _redis_client is not None and _redis_available:
        return _redis_client

    settings = get_settings()
    if not settings.redis_url:
        _redis_available = False
        return None

    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=1.0,      # Agressivo: falhar rápido
            socket_connect_timeout=1.0,
        )
        await _redis_client.ping()
        _redis_available = True
        _redis_last_failure = 0.0
        logger.info("Middleware store: Redis connected")
        return _redis_client
    except Exception as e:
        _redis_available = False
        _redis_last_failure = time.time()
        if _redis_client is not None:
            try:
                await _redis_client.aclose()
            except Exception:
                pass
            _redis_client = None
        logger.warning("Middleware store: Redis down (%s) — fallback local por %.0fs", type(e).__name__, _redis_retry_interval)
        return None


def _mark_redis_failure():
    """Marca Redis indisponivel depois de falha em op. Chamado por callers."""
    global _redis_available, _redis_last_failure, _redis_client
    _redis_available = False
    _redis_last_failure = time.time()
    if _redis_client is not None:
        try:
            import asyncio
            asyncio.ensure_future(_redis_client.aclose())
        except Exception:
            pass
        _redis_client = None


# ════════════════════════════════════════════
# Rate limiting — Redis sorted set sliding window
# ════════════════════════════════════════════

def _local_check_rate_limit(key: str, limit: int) -> bool:
    """Local fallback rate limit (single-instance only)."""
    now = time.time()
    window_start = now - 60
    if key not in _local_rate_limits:
        _local_rate_limits[key] = []
    _local_rate_limits[key] = [t for t in _local_rate_limits[key] if t > window_start]
    if len(_local_rate_limits[key]) >= limit:
        return False
    _local_rate_limits[key].append(now)
    return True


async def _check_rate_limit(key: str, limit: int) -> bool:
    """Rate limit check. Redis sorted set sliding window, local fallback."""
    r = await _get_redis()
    if not r:
        return _local_check_rate_limit(key, limit)

    redis_key = f"aion:ratelimit:{key}"
    now = time.time()
    window_start = now - 60

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zadd(redis_key, {str(now): now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, 70)
        results = await pipe.execute()

        count = results[2]
        if count > limit:
            # Over limit — remove the entry we just added
            await r.zrem(redis_key, str(now))
            return False
        return True
    except Exception:
        _mark_redis_failure()
        logger.warning("Redis rate limit failed, falling back to local")
        return _local_check_rate_limit(key, limit)


# ════════════════════════════════════════════
# Audit — Redis list per tenant, local fallback
# Hash-chaining: each entry carries prev_hash for tamper evidence (SOC 2).
# ════════════════════════════════════════════

# In-process chain tips per tenant (authoritative within one replica).
_chain_tips: dict[str, str] = {}


def _hash_entry(entry: dict) -> str:
    import hashlib
    serialized = json.dumps({k: v for k, v in entry.items() if k != "entry_hash"}, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


async def audit(action: str, request: Request, tenant: str, details: str = "") -> None:
    """Record audit event with hash chaining. Redis + local buffer.

    Each entry includes prev_hash (SHA-256 of previous entry) to form a
    tamper-evident chain. Cross-replica chains merge at the Redis layer.

    Actor identity is read from X-Aion-Actor-* headers ONLY when the request
    comes from a trusted console proxy (request.state.trusted_proxy = True).
    Direct API callers cannot spoof these headers.
    """
    prev_hash = _chain_tips.get(tenant, "0" * 64)

    # Actor headers are only trusted from console_proxy sources.
    # The middleware sets request.state.trusted_proxy before calling audit().
    trusted_source: bool = getattr(request.state, "trusted_proxy", False)

    actor_id = request.headers.get("X-Aion-Actor-Id", "")
    actor_role = request.headers.get("X-Aion-Actor-Role", "")
    auth_source = request.headers.get("X-Aion-Auth-Source", "")
    actor_reason = request.headers.get("X-Aion-Actor-Reason", "")

    entry = {
        "timestamp": time.time(),
        "action": action,
        "path": str(request.url.path),
        "method": request.method,
        "ip": request.client.host if request.client else "unknown",
        "tenant": tenant,
        "details": details,
        "prev_hash": prev_hash,
        # Actor identity — only recorded when from a trusted console proxy source
        "actor_id": actor_id if (trusted_source and actor_id) else None,
        "actor_role": actor_role if (trusted_source and actor_role) else None,
        "auth_source": auth_source if (trusted_source and auth_source) else None,
        "actor_reason": actor_reason if actor_reason else None,
        "actor_headers_trusted": trusted_source,
    }
    entry["entry_hash"] = _hash_entry(entry)
    _chain_tips[tenant] = entry["entry_hash"]

    # Always write to local buffer (fallback + fast read)
    _local_audit_log.append(entry)

    # Try Redis
    r = await _get_redis()
    if r:
        redis_key = f"aion:audit:{tenant}"
        try:
            await r.lpush(redis_key, json.dumps(entry, default=str))
            await r.ltrim(redis_key, 0, 9999)
        except Exception:
            logger.warning("Redis audit write failed")

    actor_info = f",actor={actor_id}" if actor_id else ""
    logger.info(
        '{"event":"audit","action":"%s %s","ip":"%s","tenant":"%s"%s}',
        request.method, request.url.path, entry["ip"], tenant, actor_info,
    )


async def get_audit_log(limit: int = 100, tenant: Optional[str] = None) -> list[dict]:
    """Read audit log. Redis first, local fallback."""
    r = await _get_redis()
    if r and tenant:
        redis_key = f"aion:audit:{tenant}"
        try:
            raw = await r.lrange(redis_key, 0, limit - 1)
            return [json.loads(item) for item in raw]
        except Exception:
            logger.warning("Redis audit read failed, using local")

    # Local fallback
    events = list(_local_audit_log)
    if tenant:
        events = [e for e in events if e.get("tenant") == tenant]
    return events[-limit:]


# ════════════════════════════════════════════
# Overrides — Redis hash per tenant, local fallback
# ════════════════════════════════════════════

async def set_override(key: str, value: Any, tenant: str = "default") -> None:
    """Set runtime override. Redis + local + disk (sobrevive restart sem Redis)."""
    # Local
    if tenant not in _local_overrides:
        _local_overrides[tenant] = {}
    _local_overrides[tenant][key] = value

    # Redis
    r = await _get_redis()
    redis_ok = False
    if r:
        redis_key = f"aion:overrides:{tenant}"
        try:
            await r.hset(redis_key, key, json.dumps(value))
            redis_ok = True
        except Exception:
            logger.warning("Redis override write failed")

    # Disk persistence: so se Redis nao esta disponivel (evita storage redundante)
    if not redis_ok:
        _persist_overrides_to_disk()


async def get_overrides(tenant: str = "default") -> dict:
    """Get runtime overrides. Redis first, local fallback."""
    r = await _get_redis()
    if r:
        redis_key = f"aion:overrides:{tenant}"
        try:
            data = await r.hgetall(redis_key)
            if data:
                return {k: json.loads(v) for k, v in data.items()}
        except Exception:
            logger.warning("Redis override read failed")

    return dict(_local_overrides.get(tenant, {}))


async def clear_overrides(tenant: str = "default") -> None:
    """Clear all overrides. Redis + local + disk."""
    _local_overrides.pop(tenant, None)

    r = await _get_redis()
    redis_ok = False
    if r:
        try:
            await r.delete(f"aion:overrides:{tenant}")
            redis_ok = True
        except Exception:
            pass

    if not redis_ok:
        _persist_overrides_to_disk()


# ════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════

def _is_admin_path(path: str) -> bool:
    if path in _ADMIN_EXACT:
        return True
    for prefix in _ADMIN_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


# ── URL tenant extraction ──
# Paths where the tenant is embedded as the first path segment after the prefix.
# Used to prevent cross-tenant access by mutating the URL while keeping a valid
# X-Aion-Tenant header for a different tenant.
_TENANT_EMBEDDED_PREFIXES: tuple[str, ...] = (
    "/v1/sessions/",
    "/v1/budget/",
    "/v1/intelligence/",
    "/v1/threats/",
    "/v1/benchmark/",
    "/v1/recommendations/",
    "/v1/reports/",
    "/v1/calibration/",
    "/v1/data/",
    "/v1/global/threat-feed/",
)


def _extract_path_tenant(path: str) -> Optional[str]:
    """Return the tenant segment embedded in path, or None if not applicable."""
    for prefix in _TENANT_EMBEDDED_PREFIXES:
        if path.startswith(prefix):
            remainder = path[len(prefix):]
            segment = remainder.split("/")[0]
            if segment and _TENANT_PATTERN.match(segment):
                return segment
    return None


def _requires_reason(method: str, path: str) -> bool:
    """Return True if this endpoint requires X-Aion-Actor-Reason header."""
    for m, p in _REASON_REQUIRED:
        if method == m and path.startswith(p):
            return True
    return False


def _resolve_permission(method: str, path: str) -> Optional[str]:
    """Resolve required permission for a method+path combination.

    Specific calibration actions (promote/rollback) are resolved by path suffix
    before falling through to the general prefix table.
    """
    # Calibration actions: distinguish promote from rollback by path suffix
    if method == "POST" and path.startswith("/v1/calibration/"):
        if path.endswith("/promote"):
            return "calibration:promote"
        if path.endswith("/rollback"):
            return "calibration:rollback"
    # Approval resolution
    if method == "POST" and path.startswith("/v1/approvals/") and path.endswith("/resolve"):
        return "approvals:resolve"

    for pmethod, ppath, perm in _PATH_PERMISSIONS:
        if method == pmethod and path.startswith(ppath):
            return perm
    # Default: read for GET, write for mutations
    if method == "GET":
        return "audit:read"  # safe default
    return None  # no specific permission mapped


def _build_rate_limit_key(request: Request, tenant: str, scope: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{scope}:{tenant}:{ip}"


def get_in_flight() -> int:
    return _requests_in_flight


# ════════════════════════════════════════════
# Middleware
# ════════════════════════════════════════════

class AionSecurityMiddleware(BaseHTTPMiddleware):
    """Central security layer: auth, validation, rate limiting, audit."""

    async def dispatch(self, request: Request, call_next) -> Response:
        global _requests_in_flight
        settings = get_settings()
        path = request.url.path

        if path in ("/health", "/ready", "/docs", "/openapi.json", "/metrics", "/redoc"):
            return await call_next(request)

        # In-flight limit
        if _requests_in_flight >= _MAX_IN_FLIGHT:
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "Server at capacity", "type": "capacity_exceeded", "code": "capacity_exceeded"}},
                headers={"Retry-After": "5"},
            )

        # Tenant validation
        raw_tenant = request.headers.get(settings.tenant_header)
        if raw_tenant is None:
            if settings.require_tenant:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"message": f"Missing required header: {settings.tenant_header}", "type": "invalid_request", "code": "tenant_required"}},
                )
            raw_tenant = settings.default_tenant
        tenant = raw_tenant
        if not _TENANT_PATTERN.match(tenant):
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "Invalid tenant format", "type": "invalid_request", "code": "invalid_tenant"}},
            )

        # Cross-context protection: tenant embedded in URL must match header tenant.
        # Prevents accessing /v1/sessions/other-tenant while sending X-Aion-Tenant: my-tenant.
        path_tenant = _extract_path_tenant(path)
        if path_tenant is not None and path_tenant != tenant:
            return JSONResponse(
                status_code=403,
                content={"error": {
                    "message": (
                        f"Tenant mismatch: URL references tenant '{path_tenant}' "
                        f"but request header identifies tenant '{tenant}'."
                    ),
                    "type": "auth_error",
                    "code": "tenant_mismatch",
                }},
            )

        # Auth + RBAC for admin endpoints
        if _is_admin_path(path):
            admin_key_str = getattr(settings, "admin_key", "") or ""
            # Default: not a trusted proxy source
            request.state.trusted_proxy = False
            effective_role = "no_auth"

            if admin_key_str:
                auth_header = request.headers.get("Authorization", "")
                provided_key = auth_header.removeprefix("Bearer ").strip()

                key_roles = _parse_key_roles(admin_key_str)
                if provided_key not in key_roles:
                    return JSONResponse(
                        status_code=401,
                        content={"error": {"message": "Unauthorized", "type": "auth_error", "code": "unauthorized"}},
                    )

                service_role = key_roles[provided_key]
                required_perm = _resolve_permission(request.method, path)

                # ── Trusted proxy (Gap 1+2): console_proxy keys defer RBAC to actor role ──
                # Only requests from console_proxy can provide trusted X-Aion-Actor-* headers.
                # Direct API callers with any other key role cannot inject actor headers.
                if service_role in _TRUSTED_PROXY_ROLES:
                    request.state.trusted_proxy = True
                    actor_role_hdr = request.headers.get("X-Aion-Actor-Role", "").strip()
                    if actor_role_hdr:
                        effective_role = actor_role_hdr
                    else:
                        # Console proxy without SSO context — safe default for reads
                        effective_role = Role.VIEWER
                else:
                    # Traditional service key: use key's own role for RBAC
                    effective_role = service_role

                # ── Gap 3: RBAC enforcement via effective (actor) role ──
                if required_perm and not check_permission(effective_role, required_perm):
                    return JSONResponse(
                        status_code=403,
                        content={"error": {
                            "message": (
                                f"Forbidden: role '{effective_role}' lacks permission '{required_perm}'. "
                                f"Contact your AION administrator to request elevated access."
                            ),
                            "type": "auth_error",
                            "code": "forbidden",
                        }},
                    )

                # ── Gap 4: Reason required for dangerous mutations ──
                if _requires_reason(request.method, path):
                    reason = request.headers.get("X-Aion-Actor-Reason", "").strip()
                    if not reason:
                        return JSONResponse(
                            status_code=400,
                            content={"error": {
                                "message": (
                                    "Header 'X-Aion-Actor-Reason' is required for this operation. "
                                    "Provide a human-readable justification for the audit trail."
                                ),
                                "type": "invalid_request",
                                "code": "reason_required",
                            }},
                        )

            else:
                # No key configured — block destructive operations (fail-secure).
                required_perm = _resolve_permission(request.method, path)
                if required_perm in _CRITICAL_PERMISSIONS:
                    return JSONResponse(
                        status_code=403,
                        content={"error": {
                            "message": "This operation requires authentication. Set AION_ADMIN_KEY.",
                            "type": "auth_error",
                            "code": "auth_not_configured",
                        }},
                    )

            # Rate limit admin
            rate_key = _build_rate_limit_key(request, tenant, "admin")
            if not await _check_rate_limit(rate_key, settings.admin_rate_limit):
                return JSONResponse(
                    status_code=429,
                    content={"error": {"message": "Admin rate limit exceeded", "type": "rate_limit", "code": "rate_limit_exceeded"}},
                    headers={"Retry-After": "60"},
                )

            await audit(f"{request.method} {path}", request, tenant, details=f"effective_role={effective_role}")

        # Auth + rate limit for chat endpoint
        if path == "/v1/chat/completions":
            # Optional auth for chat (enterprise mode)
            if settings.require_chat_auth:
                admin_key_str = getattr(settings, "admin_key", "") or ""
                if admin_key_str:
                    auth_header = request.headers.get("Authorization", "")
                    provided_key = auth_header.removeprefix("Bearer ").strip()
                    key_roles = _parse_key_roles(admin_key_str)
                    if provided_key not in key_roles:
                        return JSONResponse(
                            status_code=401,
                            content={"error": {"message": "Unauthorized: API key required for chat", "type": "auth_error", "code": "unauthorized"}},
                        )

            # Per-tenant rate limit (override > global default)
            tenant_overrides = await get_overrides(tenant)
            chat_limit = int(tenant_overrides.get("rate_limit", settings.chat_rate_limit))
            rate_key = _build_rate_limit_key(request, tenant, "chat")
            if not await _check_rate_limit(rate_key, chat_limit):
                return JSONResponse(
                    status_code=429,
                    content={"error": {"message": "Rate limit exceeded", "type": "rate_limit", "code": "rate_limit_exceeded"}},
                    headers={"Retry-After": "60"},
                )

        # Payload size
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > 1_048_576:
                    return JSONResponse(
                        status_code=413,
                        content={"error": {"message": "Payload too large (max 1MB)", "type": "invalid_request", "code": "payload_too_large"}},
                    )
            except ValueError:
                pass

        _requests_in_flight += 1
        try:
            response = await call_next(request)
        finally:
            _requests_in_flight -= 1

        # Inject license state header
        try:
            from aion.license import get_license, LicenseState
            lic = get_license()
            response.headers["x-aion-license"] = lic.state.value
            if lic.state == LicenseState.GRACE:
                response.headers["x-aion-license-warning"] = (
                    f"license expires in {lic.days_remaining:.0f}d — renew at contato@baluarte.ai"
                )
            elif lic.state == LicenseState.EXPIRED:
                response.headers["x-aion-license-warning"] = (
                    "license expired — running in degraded mode, contact contato@baluarte.ai"
                )
        except Exception:
            pass

        return response
