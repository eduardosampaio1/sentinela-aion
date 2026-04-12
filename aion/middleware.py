"""AION Middleware — central security, validation, rate limiting, and audit layer.

All cross-cutting concerns live here, not scattered across endpoints.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from aion.config import get_settings

logger = logging.getLogger("aion.middleware")

# Tenant validation pattern
_TENANT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Admin endpoints that require auth
_ADMIN_PATHS = {
    "/v1/killswitch",
    "/v1/estixe/intents/reload",
    "/v1/estixe/policies/reload",
    "/v1/behavior",
    "/v1/modules/",
    "/v1/overrides",
    "/v1/data/",
    "/v1/audit/",
}

# Rate limit state (in-memory — per-instance)
_rate_limits: dict[str, list[float]] = {}
_CHAT_RATE_LIMIT = 100  # per minute
_ADMIN_RATE_LIMIT = 10  # per minute

# Audit log buffer
_audit_log: list[dict] = []
_AUDIT_MAX = 5000

# Request counter for in-flight tracking
_requests_in_flight = 0
_MAX_IN_FLIGHT = 500


def _is_admin_path(path: str) -> bool:
    for admin_path in _ADMIN_PATHS:
        if path.startswith(admin_path):
            return True
    return False


def _check_rate_limit(key: str, limit: int) -> bool:
    """Check rate limit. Returns True if allowed."""
    now = time.time()
    window_start = now - 60

    if key not in _rate_limits:
        _rate_limits[key] = []

    # Clean old entries
    _rate_limits[key] = [t for t in _rate_limits[key] if t > window_start]

    if len(_rate_limits[key]) >= limit:
        return False

    _rate_limits[key].append(now)
    return True


def _audit(action: str, request: Request, tenant: str, details: str = "") -> None:
    """Record an audit event."""
    entry = {
        "timestamp": time.time(),
        "action": action,
        "path": str(request.url.path),
        "method": request.method,
        "ip": request.client.host if request.client else "unknown",
        "tenant": tenant,
        "details": details,
    }
    _audit_log.append(entry)
    if len(_audit_log) > _AUDIT_MAX:
        _audit_log.pop(0)
    logger.info("AUDIT: %s %s by %s (tenant=%s)", request.method, request.url.path, entry["ip"], tenant)


def get_audit_log(limit: int = 100) -> list[dict]:
    return _audit_log[-limit:]


def get_in_flight() -> int:
    return _requests_in_flight


class AionSecurityMiddleware(BaseHTTPMiddleware):
    """Central security layer: auth, validation, rate limiting, audit."""

    async def dispatch(self, request: Request, call_next) -> Response:
        global _requests_in_flight
        settings = get_settings()
        path = request.url.path

        # Skip for health, docs, metrics
        if path in ("/health", "/docs", "/openapi.json", "/metrics"):
            return await call_next(request)

        # --- In-flight limit ---
        if _requests_in_flight >= _MAX_IN_FLIGHT:
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "Server at capacity", "type": "capacity_exceeded", "code": "capacity_exceeded"}},
                headers={"Retry-After": "5"},
            )

        # --- Tenant validation ---
        tenant = request.headers.get(settings.tenant_header, settings.default_tenant)
        if not _TENANT_PATTERN.match(tenant):
            return JSONResponse(
                status_code=400,
                content={"error": {"message": f"Invalid tenant format: must match [a-zA-Z0-9_-]{{1,64}}", "type": "invalid_request", "code": "invalid_tenant"}},
            )

        # --- Auth for admin endpoints ---
        if _is_admin_path(path):
            admin_key = settings.__dict__.get("admin_key") or ""
            if admin_key:
                auth_header = request.headers.get("Authorization", "")
                provided_key = auth_header.removeprefix("Bearer ").strip()
                # Support multiple keys for rotation
                valid_keys = [k.strip() for k in admin_key.split(",") if k.strip()]
                if provided_key not in valid_keys:
                    return JSONResponse(
                        status_code=401,
                        content={"error": {"message": "Unauthorized", "type": "auth_error", "code": "unauthorized"}},
                    )

            # Rate limit admin
            rate_key = f"admin:{request.client.host if request.client else 'unknown'}"
            if not _check_rate_limit(rate_key, _ADMIN_RATE_LIMIT):
                return JSONResponse(
                    status_code=429,
                    content={"error": {"message": "Rate limit exceeded", "type": "rate_limit", "code": "rate_limit_exceeded"}},
                    headers={"Retry-After": "60"},
                )

            # Audit admin actions
            _audit(f"{request.method} {path}", request, tenant)

        # --- Rate limit for chat endpoint ---
        if path == "/v1/chat/completions":
            rate_key = f"chat:{tenant}:{request.client.host if request.client else 'unknown'}"
            if not _check_rate_limit(rate_key, _CHAT_RATE_LIMIT):
                return JSONResponse(
                    status_code=429,
                    content={"error": {"message": "Rate limit exceeded", "type": "rate_limit", "code": "rate_limit_exceeded"}},
                    headers={"Retry-After": "60"},
                )

        # --- Payload size limit ---
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 1_048_576:  # 1MB
            return JSONResponse(
                status_code=413,
                content={"error": {"message": "Payload too large (max 1MB)", "type": "invalid_request", "code": "payload_too_large"}},
            )

        # --- Execute request ---
        _requests_in_flight += 1
        try:
            response = await call_next(request)
            return response
        finally:
            _requests_in_flight -= 1
