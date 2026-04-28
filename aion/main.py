"""AION — Motor Realtime do Sentinela.

FastAPI application serving as an OpenAI-compatible proxy gateway.
Modes: Normal | Degraded | Safe (SAFE_MODE)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from aion import __version__
from aion.config import get_settings
from aion.middleware import AionSecurityMiddleware
from aion.pipeline import Pipeline, build_pipeline
from aion.proxy import forward_request, forward_request_stream, shutdown_client
from aion.shared.telemetry import shutdown_telemetry

logger = logging.getLogger("aion")

# --- Global state ---
_pipeline: Pipeline | None = None

# Background task handles
_snapshot_task: asyncio.Task | None = None
_approval_task: asyncio.Task | None = None
_trust_guard_task: asyncio.Task | None = None


async def _snapshot_baselines_loop():
    """Background task: snapshot baselines hourly for trend computation."""
    while True:
        await asyncio.sleep(3600)
        try:
            from aion.nemos import get_nemos
            await get_nemos().snapshot_baselines_if_needed()
        except Exception:
            logger.debug("NEMOS snapshot failed (non-critical)", exc_info=True)


async def _approval_sweep_loop():
    """Background task: resolve expired approvals every 60s via their on_timeout policy."""
    while True:
        await asyncio.sleep(60)
        try:
            await _sweep_expired_approvals()
        except Exception:
            logger.debug("Approval sweep failed (non-critical)", exc_info=True)


async def _sweep_expired_approvals() -> int:
    """Check all pending approvals; resolve expired ones per on_timeout. Returns count resolved."""
    import time as _time
    from aion.nemos import get_nemos
    nemos = get_nemos()
    keys = await nemos._store.keys_by_prefix("aion:approval:")
    now = _time.time()
    resolved = 0
    for key in keys:
        record = await nemos._store.get_json(key)
        if not record or record.get("status") != "pending":
            continue
        if record.get("expires_at", 0) > now:
            continue
        on_timeout = record.get("on_timeout", "block")
        if on_timeout == "block":
            record["status"] = "expired"
        else:
            record["status"] = "timeout_fallback"
        record["resolved_by"] = "system:timeout"
        record["resolved_at"] = now
        await nemos._store.set_json(key, record, ttl_seconds=7 * 86400)
        resolved += 1
        logger.info("Approval %s resolved via timeout (on_timeout=%s)",
                    record.get("approval_request_id"), on_timeout)
    return resolved


_pipeline_ready = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    global _pipeline

    settings = get_settings()
    log_format = '{"time":"%(asctime)s","name":"%(name)s","level":"%(levelname)s","message":"%(message)s"}'
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=log_format,
    )

    logger.info("AION v%s starting on port %d", __version__, settings.port)
    logger.info("Fail mode: %s", settings.fail_mode.value)
    logger.info(
        "Modules: ESTIXE=%s NOMOS=%s METIS=%s",
        settings.estixe_enabled,
        settings.nomos_enabled,
        settings.metis_enabled,
    )

    # ── Fail-fast: warn loudly on missing critical secrets ─────────────────────
    _env_problems: list[str] = []
    if not settings.admin_key:
        _env_problems.append(
            "AION_ADMIN_KEY is not set — all admin/control-plane endpoints are "
            "unauthenticated. Set AION_ADMIN_KEY=yourkey:admin before production."
        )
    if not os.environ.get("AION_SESSION_AUDIT_SECRET"):
        _env_problems.append(
            "AION_SESSION_AUDIT_SECRET is not set — audit trail HMAC signatures are "
            "disabled (tamper evidence theater). Set a 32+ char random secret."
        )
    if _env_problems:
        logger.warning("=" * 72)
        logger.warning("AION SECURITY WARNINGS — resolve before production:")
        for _p in _env_problems:
            logger.warning("  ⚠  %s", _p)
        logger.warning("=" * 72)
    # ───────────────────────────────────────────────────────────────────────────

    from aion.license import validate_license_or_abort, LicenseState
    lic = validate_license_or_abort()

    if lic.state == LicenseState.EXPIRED:
        logger.warning("Licença expirada — desabilitando NOMOS e METIS avançado (fail-open)")
        settings.nomos_enabled = False
        settings.metis_enabled = False

    # ── Trust Guard: startup validation (license claims + integrity manifest) ─
    from aion.trust_guard import startup_validation
    _trust_state = await startup_validation()

    from aion.middleware import _load_overrides_from_disk
    _load_overrides_from_disk()

    try:
        from aion.observability import setup_telemetry
        setup_telemetry(app)
    except Exception as e:
        logger.warning("OpenTelemetry setup failed (non-fatal): %s", e)

    _pipeline = build_pipeline()

    if settings.estixe_enabled and not settings.safe_mode:
        t0 = time.perf_counter()
        for module in _pipeline._pre_modules:
            if module.name == "estixe":
                try:
                    await module.initialize()
                    logger.info("Cold start: ESTIXE initialized in %.1fs", time.perf_counter() - t0)
                except Exception:
                    logger.exception("Cold start: ESTIXE initialization failed")
                break

    _pipeline_ready.set()
    logger.info("AION pipeline ready")

    # ── Trust Guard: apply entitlement from startup state + launch loop ───────
    global _snapshot_task, _approval_task, _trust_guard_task
    try:
        from aion.trust_guard.entitlement_engine import EntitlementEngine, TrustViolationBehavior
        from aion.config import get_trust_guard_settings
        _tg_settings = get_trust_guard_settings()
        if _tg_settings.enabled:
            _behavior = TrustViolationBehavior(_tg_settings.violation_behavior)
            EntitlementEngine.apply(_pipeline, _trust_state, _behavior)
            from aion.trust_guard import start_trust_guard_loop
            _trust_guard_task = start_trust_guard_loop(_pipeline)
    except Exception as _tg_err:
        logger.warning("Trust Guard startup failed (non-fatal): %s", _tg_err)

    _snapshot_task = asyncio.create_task(_snapshot_baselines_loop())
    _approval_task = asyncio.create_task(_approval_sweep_loop())

    yield

    if _snapshot_task:
        _snapshot_task.cancel()
    if _approval_task:
        _approval_task.cancel()
    if _trust_guard_task:
        _trust_guard_task.cancel()

    await shutdown_telemetry()
    await shutdown_client()
    logger.info("AION shutdown complete")


# ── Security headers middleware ──

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app = FastAPI(
    title="AION",
    description="Motor Realtime do Sentinela — AI Control Plane. "
                "Proxy gateway OpenAI-compatible com controle de PII, routing inteligente, e otimização de prompt.",
    version=__version__,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "LLM Proxy", "description": "OpenAI-compatible chat completions"},
        {"name": "Control Plane", "description": "Runtime configuration: killswitch, overrides, behavior dial, module toggle"},
        {"name": "Observability", "description": "Health, stats, events, metrics, economics, explainability"},
        {"name": "Data Management", "description": "LGPD compliance: data deletion, audit trail"},
    ],
)

# Register middleware stack (order matters: last added = first executed)
app.add_middleware(AionSecurityMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# CORS
_settings_cors = get_settings()
if _settings_cors.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _settings_cors.cors_origins.split(",")],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Aion-Decision", "X-Request-ID", "X-Aion-Route-Reason", "X-Aion-Mode", "X-Aion-Replica", "X-Aion-Pipeline-Ms", "X-Aion-Total-Ms", "X-Aion-Verified"],
    )


# Global exception handlers
@app.exception_handler(RequestValidationError)
async def _handle_request_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"message": f"Request validation error: {exc}", "type": "invalid_request_error", "code": "validation_error"}},
    )


# Register routers
from aion.routers import proxy, observability, control_plane, budget, sessions, approvals, intelligence, reports, data_mgmt, global_feed, collective  # noqa: E402

app.include_router(proxy.router)
app.include_router(observability.router)
app.include_router(control_plane.router)
app.include_router(budget.router)
app.include_router(sessions.router)
app.include_router(approvals.router)
app.include_router(intelligence.router)
app.include_router(reports.router)
app.include_router(data_mgmt.router)
app.include_router(global_feed.router)
app.include_router(collective.router)
