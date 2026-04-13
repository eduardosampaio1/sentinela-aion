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
_ADMIN_EXACT = {"/v1/killswitch", "/v1/behavior", "/v1/overrides", "/v1/audit"}
_ADMIN_PREFIXES = ("/v1/estixe/", "/v1/modules/", "/v1/data/", "/v1/audit/")

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
]

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

# ── Limits ──
_CHAT_RATE_LIMIT = 100
_ADMIN_RATE_LIMIT = 10
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


# ════════════════════════════════════════════
# Redis client (async, lazy — same as behavior.py)
# ════════════════════════════════════════════

async def _get_redis():
    """Get or create async Redis client. Returns None if unavailable."""
    global _redis_client, _redis_available
    if _redis_client is not None:
        return _redis_client if _redis_available else None

    settings = get_settings()
    if not settings.redis_url:
        _redis_available = False
        return None

    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=2.0
        )
        await _redis_client.ping()
        _redis_available = True
        logger.info("Middleware store: Redis connected (cluster-safe)")
        return _redis_client
    except Exception:
        _redis_available = False
        logger.warning("Middleware store: Redis unavailable, using local fallback")
        return None


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
        logger.warning("Redis rate limit failed, falling back to local")
        return _local_check_rate_limit(key, limit)


# ════════════════════════════════════════════
# Audit — Redis list per tenant, local fallback
# ════════════════════════════════════════════

async def audit(action: str, request: Request, tenant: str, details: str = "") -> None:
    """Record audit event. Redis + local buffer."""
    entry = {
        "timestamp": time.time(),
        "action": action,
        "path": str(request.url.path),
        "method": request.method,
        "ip": request.client.host if request.client else "unknown",
        "tenant": tenant,
        "details": details,
    }

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

    logger.info(
        '{"event":"audit","action":"%s %s","ip":"%s","tenant":"%s"}',
        request.method, request.url.path, entry["ip"], tenant,
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
    """Set runtime override. Redis + local."""
    # Local
    if tenant not in _local_overrides:
        _local_overrides[tenant] = {}
    _local_overrides[tenant][key] = value

    # Redis
    r = await _get_redis()
    if r:
        redis_key = f"aion:overrides:{tenant}"
        try:
            await r.hset(redis_key, key, json.dumps(value))
        except Exception:
            logger.warning("Redis override write failed")


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
    """Clear all overrides. Redis + local."""
    _local_overrides.pop(tenant, None)

    r = await _get_redis()
    if r:
        try:
            await r.delete(f"aion:overrides:{tenant}")
        except Exception:
            pass


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


def _resolve_permission(method: str, path: str) -> Optional[str]:
    """Resolve required permission for a method+path combination."""
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

        if path in ("/health", "/docs", "/openapi.json", "/metrics", "/redoc"):
            return await call_next(request)

        # In-flight limit
        if _requests_in_flight >= _MAX_IN_FLIGHT:
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "Server at capacity", "type": "capacity_exceeded", "code": "capacity_exceeded"}},
                headers={"Retry-After": "5"},
            )

        # Tenant validation
        tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
        if not _TENANT_PATTERN.match(tenant):
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "Invalid tenant format", "type": "invalid_request", "code": "invalid_tenant"}},
            )

        # Auth + RBAC for admin endpoints
        if _is_admin_path(path):
            admin_key_str = getattr(settings, "admin_key", "") or ""
            if admin_key_str:
                auth_header = request.headers.get("Authorization", "")
                provided_key = auth_header.removeprefix("Bearer ").strip()

                key_roles = _parse_key_roles(admin_key_str)
                if provided_key not in key_roles:
                    return JSONResponse(
                        status_code=401,
                        content={"error": {"message": "Unauthorized", "type": "auth_error", "code": "unauthorized"}},
                    )

                # RBAC: check if this key's role has permission for this endpoint
                role = key_roles[provided_key]
                required_perm = _resolve_permission(request.method, path)
                if required_perm and not check_permission(role, required_perm):
                    return JSONResponse(
                        status_code=403,
                        content={"error": {
                            "message": f"Forbidden: role '{role}' lacks '{required_perm}'",
                            "type": "auth_error",
                            "code": "forbidden",
                        }},
                    )

            # Rate limit admin
            rate_key = _build_rate_limit_key(request, tenant, "admin")
            if not await _check_rate_limit(rate_key, _ADMIN_RATE_LIMIT):
                return JSONResponse(
                    status_code=429,
                    content={"error": {"message": "Admin rate limit exceeded", "type": "rate_limit", "code": "rate_limit_exceeded"}},
                    headers={"Retry-After": "60"},
                )

            await audit(f"{request.method} {path}", request, tenant, details=f"role={key_roles.get(provided_key, 'unknown') if admin_key_str else 'no_auth'}")

        # Rate limit chat
        if path == "/v1/chat/completions":
            rate_key = _build_rate_limit_key(request, tenant, "chat")
            if not await _check_rate_limit(rate_key, _CHAT_RATE_LIMIT):
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
            return await call_next(request)
        finally:
            _requests_in_flight -= 1
