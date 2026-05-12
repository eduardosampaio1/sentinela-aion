"""KAIROS sanitized telemetry exporter — opt-in, Sentinela Cloud only.

Zero data leaves the client environment unless all of the following are true:
  1. KAIROS_TELEMETRY_ENABLED=true
  2. KAIROS_TELEMETRY_ENDPOINT is set (e.g. https://telemetry.sentinela.io/v1/ingest)
  3. KAIROS_TELEMETRY_API_KEY is set

What CAN leave the perimeter (sanitized metadata only):
  - SHA-256 hashes of identifiers (candidate_id, tenant_id) — never raw
  - template_id — only if it matches the public catalog pattern (alphanumeric/underscore/hyphen,
    max 64 chars); unknown IDs are omitted
  - policy_type — only known values: bypass | guardrail | route_to_api | handoff
  - lifecycle transition metadata (from_status, to_status, actor_type)
  - shadow run aggregate metrics (match rate, fallback rate, obs bucket)
  - AION version string
  - Timestamp bucketed to the nearest hour (no finer granularity)

What NEVER leaves the perimeter:
  - Raw prompts, responses, or any content
  - PII of any kind (names, CPF, email, pix keys, etc.)
  - Full policy payload (trigger conditions, actions, exclusions, summaries)
  - Raw tenant_id, candidate_id, or any client identifier
  - actor_id (operator ID)
  - Secrets, tokens, API keys
  - Raw evidence references or business/technical summaries
  - Rejection reasons (may contain customer context)

Runtime kill-switch:
  To disable telemetry at runtime without restart, call:
      from aion.kairos.settings import reset_kairos_settings
      from aion.kairos.telemetry import reset_telemetry_exporter
      reset_kairos_settings()   # forces re-read of env vars
      reset_telemetry_exporter()  # discards cached exporter
  The next event will construct a new exporter with updated settings.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aion.kairos.models import PolicyCandidate, ShadowRun
    from aion.kairos.settings import KairosSettings

logger = logging.getLogger("aion.kairos.telemetry")

_AION_VERSION: Optional[str] = None

# Allowlists — controls what leaves the perimeter
_KNOWN_POLICY_TYPES = frozenset({"bypass", "guardrail", "route_to_api", "handoff"})
_KNOWN_ACTOR_TYPES = frozenset({"operator", "sweep", "system"})
_KNOWN_STATUSES = frozenset({
    "draft", "ready_for_shadow", "shadow_running", "shadow_completed",
    "approved_production", "under_review", "rejected", "deprecated", "archived",
})
_SAFE_TEMPLATE_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


def _get_aion_version() -> str:
    global _AION_VERSION
    if _AION_VERSION is None:
        try:
            from importlib.metadata import version
            _AION_VERSION = version("aion")
        except Exception:
            _AION_VERSION = "unknown"
    return _AION_VERSION


def _hash(value: str) -> str:
    """SHA-256 of value, hex-encoded. One-way only — never reversed."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bucket_timestamp(dt: datetime) -> str:
    """Round datetime to the nearest hour. Converts naive datetimes to UTC first."""
    if dt.tzinfo is None:
        # Treat naive as UTC (callers must pass timezone-aware; this is a safe fallback)
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    bucketed = dt_utc.replace(minute=0, second=0, microsecond=0)
    return bucketed.isoformat()


def _bucket_observations(count: int) -> str:
    """Bucket observation count into a range string to avoid leaking exact request volume."""
    thresholds = [0, 100, 250, 500, 1_000, 2_500, 5_000, 10_000]
    for i, low in enumerate(thresholds):
        high = thresholds[i + 1] if i + 1 < len(thresholds) else None
        if high is None or count < high:
            return f"{low}-{high}" if high else f"{low}+"
    return f"{thresholds[-1]}+"


def _sanitize_policy_type(policy_type: str) -> Optional[str]:
    """Return policy_type only if it's a known public value; otherwise None."""
    return policy_type if policy_type in _KNOWN_POLICY_TYPES else None


def _sanitize_template_id(template_id: Optional[str]) -> Optional[str]:
    """Return template_id only if it matches the safe public catalog pattern."""
    if template_id and _SAFE_TEMPLATE_ID_RE.match(template_id):
        return template_id
    return None


def _sanitize_actor_type(actor_type: str) -> Optional[str]:
    """Return actor_type only if it's a known public value; otherwise None."""
    return actor_type if actor_type in _KNOWN_ACTOR_TYPES else None


def _sanitize_status(status: Optional[str]) -> Optional[str]:
    """Return status only if it's a known state machine value; otherwise None."""
    if status is None:
        return None
    return status if status in _KNOWN_STATUSES else None


def _safe_rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator > 0:
        return round(numerator / denominator, 4)
    return None


def _build_payload(
    candidate: "PolicyCandidate",
    from_status: Optional[str],
    to_status: str,
    actor_type: str,
    shadow_run: Optional["ShadowRun"] = None,
) -> dict:
    """Build a sanitized telemetry payload. No raw identifiers, no PII."""
    payload: dict = {
        "event": "lifecycle_transition",
        "candidate_id_hash": _hash(candidate.id),
        "template_id": _sanitize_template_id(candidate.template_id),
        "policy_type": _sanitize_policy_type(candidate.type),
        "from_status": _sanitize_status(from_status),
        "to_status": _sanitize_status(to_status),
        "actor_type": _sanitize_actor_type(actor_type),
        "aion_version": _get_aion_version(),
        "install_hash": _hash(candidate.tenant_id),  # hashed — never raw tenant_id
        "timestamp_bucket": _bucket_timestamp(datetime.now(timezone.utc)),
    }

    if shadow_run is not None:
        obs = shadow_run.observations_count
        payload["shadow_match_rate"] = _safe_rate(shadow_run.matched_count, obs)
        payload["shadow_fallback_rate"] = _safe_rate(shadow_run.fallback_count, obs)
        payload["shadow_observations_bucket"] = _bucket_observations(obs)

    return payload


def _validate_api_key(api_key: str) -> str:
    """Validate api_key has no control characters that could enable header injection."""
    if any(c in api_key for c in ("\n", "\r", "\x00")):
        raise ValueError("KAIROS_TELEMETRY_API_KEY contains invalid control characters")
    return api_key


class KairosTelemetryExporter:
    """Fire-and-forget sanitized telemetry sender.

    Only sends when telemetry_enabled=True and endpoint+api_key are configured.
    Never raises into the caller — all errors caught and logged at DEBUG level.

    Settings are read from the KairosSettings passed at construction. The singleton
    caches these settings. For a runtime kill-switch without restart, call:
        reset_telemetry_exporter() + reset_kairos_settings()
    and the next event will build a fresh exporter with updated settings.
    """

    def __init__(self, settings: "KairosSettings") -> None:
        self._enabled = settings.telemetry_enabled
        self._endpoint = (settings.telemetry_endpoint or "").rstrip("/")
        raw_key = settings.telemetry_api_key or ""
        try:
            self._api_key = _validate_api_key(raw_key)
        except ValueError:
            logger.warning("KAIROS_TELEMETRY_API_KEY contains invalid characters; telemetry disabled")
            self._api_key = ""

    @property
    def active(self) -> bool:
        return self._enabled and bool(self._endpoint) and bool(self._api_key)

    async def emit_lifecycle_transition(
        self,
        candidate: "PolicyCandidate",
        from_status: Optional[str],
        to_status: str,
        actor_type: str,
        shadow_run: Optional["ShadowRun"] = None,
    ) -> None:
        """Emit a sanitized lifecycle_transition event.

        No-op when telemetry is disabled. Errors are logged at DEBUG and swallowed.
        """
        if not self.active:
            return

        try:
            payload = _build_payload(candidate, from_status, to_status, actor_type, shadow_run)
            await self._send(payload)
        except Exception:
            # exc_info intentionally omitted: _send handles its own exceptions safely;
            # exc_info here could expose api_key via _send's frame locals in log aggregators.
            logger.debug("KAIROS telemetry: failed to emit event (non-critical)")

    async def _send(self, payload: dict) -> None:
        """HTTP POST payload to the configured endpoint."""
        import httpx

        url = f"{self._endpoint}/events"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Aion-Telemetry-Version": "1",
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=2, read=3, write=2, pool=1)) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                logger.debug("KAIROS telemetry: event emitted → %s", resp.status_code)
        except httpx.HTTPStatusError as exc:
            # Log status code only — do NOT log headers (contains api_key)
            logger.debug(
                "KAIROS telemetry: server returned %s (non-critical)",
                exc.response.status_code,
            )
        except httpx.RequestError as exc:
            # Network error — log type only, not the request (headers may contain api_key)
            logger.debug(
                "KAIROS telemetry: network error %s (non-critical)",
                type(exc).__name__,
            )


# ── Singleton ──────────────────────────────────────────────────────────────────

_exporter: Optional[KairosTelemetryExporter] = None


def get_telemetry_exporter() -> KairosTelemetryExporter:
    """Return (or lazily create) the telemetry exporter singleton."""
    global _exporter
    if _exporter is None:
        from aion.kairos.settings import get_kairos_settings
        _exporter = KairosTelemetryExporter(get_kairos_settings())
    return _exporter


def reset_telemetry_exporter() -> None:
    """Reset singleton — for testing or runtime kill-switch (pair with reset_kairos_settings())."""
    global _exporter
    _exporter = None
