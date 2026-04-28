"""AION Collective router — editorial policy exchange.

Phase 1: AION Editorial Exchange only.
- Catalog served from config/collective/collective_policies.yaml (bundled, no DB required).
- Install status tracked in Redis: aion:collective:{tenant}:installs:{policy_id}
- No telemetry collection in Phase 1 (telemetry enters in Shadow Mode phase).

External policy packs (Fase 3):
- Signed JSON bundles verified via Sentinela Policy Pack Signing Key.
- Stored in Redis: aion:collective:packs:{pack_id}
- Policies from loaded packs appear in the browse endpoint alongside bundled policies.

Endpoints:
    GET    /v1/collective/policies               → browse bundled + loaded pack policies
    GET    /v1/collective/policies/{id}          → policy detail with provenance
    POST   /v1/collective/packs                  → load a signed external policy pack (admin)
    GET    /v1/collective/packs                  → list loaded external packs (admin)
    DELETE /v1/collective/packs/{pack_id}        → remove a loaded pack (admin)
    GET    /v1/collective/installed/{tenant}     → installed policies with status
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, HTTPException, Request

from aion.collective.models import CollectivePolicy, CollectivePolicyMetrics, InstalledCollectivePolicy, PolicyProvenance

logger = logging.getLogger("aion.collective")

router = APIRouter()

# Redis key helpers for external policy packs
_PACK_KEY_PREFIX = "aion:collective:packs:"
_PACK_TTL = 365 * 86400  # 1 year

# ── Catalog loading ───────────────────────────────────────────────────────────

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "config" / "collective" / "collective_policies.yaml"


@lru_cache(maxsize=1)
def _load_catalog() -> list[CollectivePolicy]:
    """Load editorial policies from YAML. Cached for the process lifetime.

    Returns an empty list (graceful degradation) if the file is missing or malformed.
    """
    if not _CATALOG_PATH.exists():
        logger.warning("collective_policies.yaml not found at %s — catalog empty", _CATALOG_PATH)
        return []

    try:
        raw: list[dict[str, Any]] = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8")) or []
    except Exception:
        logger.exception("Failed to parse collective_policies.yaml")
        return []

    policies: list[CollectivePolicy] = []
    for entry in raw:
        try:
            provenance_data = entry.get("provenance", {})
            metrics_data = entry.get("metrics", {})
            policy = CollectivePolicy(
                id=entry["id"],
                name=entry["name"],
                description=entry["description"],
                sectors=entry.get("sectors", []),
                editorial=entry.get("editorial", True),
                risk_level=entry.get("risk_level", "low"),
                reversible=entry.get("reversible", True),
                provenance=PolicyProvenance(**provenance_data),
                metrics=CollectivePolicyMetrics(**metrics_data),
            )
            policies.append(policy)
        except Exception:
            logger.warning("Skipping malformed catalog entry: %s", entry.get("id", "<unknown>"), exc_info=True)

    logger.info("AION Collective: loaded %d editorial policies", len(policies))
    return policies


def _get_catalog() -> list[CollectivePolicy]:
    """Return the cached bundled catalog."""
    return _load_catalog()


# ── External policy packs (Redis) ─────────────────────────────────────────────

async def _store_pack(pack_id: str, pack_data: dict) -> None:
    try:
        from aion.middleware import _redis_client, _redis_available
        if _redis_available and _redis_client:
            await _redis_client.set(
                f"{_PACK_KEY_PREFIX}{pack_id}",
                json.dumps(pack_data),
                ex=_PACK_TTL,
            )
    except Exception:
        logger.debug("Failed to store policy pack %s in Redis", pack_id, exc_info=True)


async def _get_pack(pack_id: str) -> Optional[dict]:
    try:
        from aion.middleware import _redis_client, _redis_available
        if _redis_available and _redis_client:
            raw = await _redis_client.get(f"{_PACK_KEY_PREFIX}{pack_id}")
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    return None


async def _delete_pack(pack_id: str) -> bool:
    try:
        from aion.middleware import _redis_client, _redis_available
        if _redis_available and _redis_client:
            deleted = await _redis_client.delete(f"{_PACK_KEY_PREFIX}{pack_id}")
            return deleted > 0
    except Exception:
        pass
    return False


async def _list_packs() -> list[dict]:
    result = []
    try:
        from aion.middleware import _redis_client, _redis_available
        if not (_redis_available and _redis_client):
            return result
        async for key in _redis_client.scan_iter(match=f"{_PACK_KEY_PREFIX}*"):
            raw = await _redis_client.get(key)
            if raw:
                try:
                    data = json.loads(raw)
                    result.append({
                        "pack_id":      data.get("pack_id", ""),
                        "name":         data.get("name", ""),
                        "publisher":    data.get("publisher", ""),
                        "published_at": data.get("published_at", ""),
                        "policy_count": len(data.get("policies", [])),
                        "loaded_at":    data.get("loaded_at", 0),
                    })
                except Exception:
                    pass
    except Exception:
        logger.debug("Redis unavailable for pack listing", exc_info=True)
    return sorted(result, key=lambda x: x["loaded_at"], reverse=True)


async def _get_pack_policies() -> list[CollectivePolicy]:
    """Load all policies from all Redis-stored external packs.

    Each policy gets a source tag in its provenance (author field) so the
    browse endpoint can surface where it came from.
    """
    policies: list[CollectivePolicy] = []
    try:
        from aion.middleware import _redis_client, _redis_available
        if not (_redis_available and _redis_client):
            return policies
        async for key in _redis_client.scan_iter(match=f"{_PACK_KEY_PREFIX}*"):
            raw = await _redis_client.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
                pack_id = data.get("pack_id", "")
                publisher = data.get("publisher", "")
                for entry in data.get("policies", []):
                    try:
                        provenance_data = entry.get("provenance", {
                            "version": "1.0",
                            "last_updated": data.get("published_at", ""),
                            "author": f"{publisher} (pack:{pack_id})",
                            "signed_by_aion": True,
                            "changelog": [],
                        })
                        policy = CollectivePolicy(
                            id=entry["id"],
                            name=entry.get("name", entry["id"]),
                            description=entry.get("description", ""),
                            sectors=entry.get("sectors", []),
                            editorial=entry.get("editorial", False),
                            risk_level=entry.get("risk_level", "low"),
                            reversible=entry.get("reversible", True),
                            provenance=PolicyProvenance(**provenance_data),
                            metrics=CollectivePolicyMetrics(
                                **entry.get("metrics", {})
                            ),
                        )
                        policies.append(policy)
                    except Exception:
                        logger.debug("Skipping malformed pack policy: %s", entry.get("id"), exc_info=True)
            except Exception:
                logger.debug("Failed to parse pack from key %s", key, exc_info=True)
    except Exception:
        logger.debug("Redis unavailable for pack policies", exc_info=True)
    return policies


# ── Redis helpers ─────────────────────────────────────────────────────────────

def _install_key(tenant: str, policy_id: str) -> str:
    return f"aion:collective:{tenant}:installs:{policy_id}"


def _installs_pattern(tenant: str) -> str:
    return f"aion:collective:{tenant}:installs:*"


async def _get_install_status(tenant: str, policy_id: str) -> Optional[str]:
    """Return install status ('sandbox'|'shadow'|'production') or None."""
    try:
        from aion.middleware import _redis_client, _redis_available
        if _redis_available and _redis_client:
            raw = await _redis_client.get(_install_key(tenant, policy_id))
            if raw:
                data = json.loads(raw)
                return data.get("status")
    except Exception:
        pass
    return None


async def _get_all_installs(tenant: str) -> list[InstalledCollectivePolicy]:
    """Retrieve all installed policies for a tenant from Redis."""
    result: list[InstalledCollectivePolicy] = []
    try:
        from aion.middleware import _redis_client, _redis_available
        if not (_redis_available and _redis_client):
            return result
        pattern = _installs_pattern(tenant)
        async for key in _redis_client.scan_iter(match=pattern):
            raw = await _redis_client.get(key)
            if raw:
                try:
                    data = json.loads(raw)
                    result.append(InstalledCollectivePolicy(**data))
                except Exception:
                    pass
    except Exception:
        logger.debug("Redis unavailable for collective installs query", exc_info=True)
    return result


async def _write_install(install: InstalledCollectivePolicy) -> None:
    """Persist install record to Redis (TTL: 365 days)."""
    try:
        from aion.middleware import _redis_client, _redis_available
        if _redis_available and _redis_client:
            key = _install_key(install.tenant, install.policy_id)
            await _redis_client.set(key, install.model_dump_json(), ex=31_536_000)  # 365d
    except Exception:
        logger.debug("Failed to persist collective install to Redis", exc_info=True)


# ── Endpoints ─────────────────────────────────────────────────────────────────

# ── Policy pack endpoints (auth handled by middleware via _ADMIN_EXACT prefix) ─

@router.post("/v1/collective/packs", tags=["Collective"])
async def load_policy_pack(request: Request):
    """Load a signed external policy pack.

    Body: raw JSON bytes of the signed policy pack.
    Verifies the Sentinela Policy Pack Signing Key signature before storing.
    Requires admin auth (handled by AionSecurityMiddleware).
    """
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="Request body is empty")

    from aion.trust_guard.policy_pack_verifier import verify_policy_pack_bytes
    result = verify_policy_pack_bytes(raw)

    if not result.verified:
        raise HTTPException(
            status_code=422,
            detail=f"Policy pack signature invalid: {result.reason}",
        )

    # Store in Redis with metadata
    pack_data = json.loads(raw)
    pack_data["loaded_at"] = time.time()
    await _store_pack(result.pack_id, pack_data)

    logger.info(
        "Collective: external pack loaded — pack_id=%s publisher=%s policies=%d",
        result.pack_id, result.publisher, result.policy_count,
    )

    return {
        "pack_id":      result.pack_id,
        "name":         result.name,
        "publisher":    result.publisher,
        "published_at": result.published_at,
        "policy_count": result.policy_count,
        "status":       "loaded",
    }


@router.get("/v1/collective/packs", tags=["Collective"])
async def list_policy_packs():
    """List all loaded external policy packs. Requires admin auth."""
    packs = await _list_packs()
    return {"packs": packs, "count": len(packs)}


@router.delete("/v1/collective/packs/{pack_id}", tags=["Collective"])
async def remove_policy_pack(pack_id: str):
    """Remove a loaded external policy pack. Requires admin auth."""
    deleted = await _delete_pack(pack_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Pack '{pack_id}' not found")
    logger.info("Collective: external pack removed — pack_id=%s", pack_id)
    return {"pack_id": pack_id, "status": "removed"}


@router.get("/v1/collective/policies", tags=["Collective"])
async def browse_collective_policies(
    sector: Optional[str] = None,
    request: Request = None,
):
    """Browse AION Editorial Exchange policies.

    Optional query params:
    - sector: filter by sector name (case-insensitive). 'all' or omit = no filter.
    """
    catalog = _get_catalog()

    if sector and sector.lower() not in ("all", "todos"):
        sector_lower = sector.lower()
        catalog = [p for p in catalog if sector_lower in [s.lower() for s in p.sectors]]

    # Merge bundled catalog + external pack policies (deduplicate by id, bundled wins)
    pack_policies = await _get_pack_policies()
    bundled_ids = {p.id for p in catalog}
    combined = list(catalog) + [p for p in pack_policies if p.id not in bundled_ids]

    if sector and sector.lower() not in ("all", "todos"):
        sector_lower = sector.lower()
        combined = [p for p in combined if sector_lower in [s.lower() for s in p.sectors]]

    # Annotate with install status for the requesting tenant (best-effort)
    tenant = "default"
    if request is not None:
        from aion.config import get_settings
        tenant = request.headers.get(get_settings().tenant_header, get_settings().default_tenant)

    enriched = []
    for policy in combined:
        status = await _get_install_status(tenant, policy.id)
        p = policy.model_copy(update={"installed_status": status})
        enriched.append(p)

    return {
        "policies": [p.model_dump() for p in enriched],
        "count": len(enriched),
        "sector_filter": sector,
        "phase": "editorial",
    }


@router.get("/v1/collective/policies/{policy_id}", tags=["Collective"])
async def get_collective_policy(policy_id: str, request: Request):
    """Get full detail for a specific editorial policy, including provenance and metrics."""
    catalog = _get_catalog()
    policy = next((p for p in catalog if p.id == policy_id), None)
    if policy is None:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found in collective catalog")

    # Annotate with install status
    tenant = "default"
    from aion.config import get_settings
    tenant = request.headers.get(get_settings().tenant_header, get_settings().default_tenant)
    status = await _get_install_status(tenant, policy.id)
    policy = policy.model_copy(update={"installed_status": status})

    return policy.model_dump()


@router.post("/v1/collective/policies/{policy_id}/install", tags=["Collective"])
async def install_collective_policy(policy_id: str, request: Request):
    """Install a Collective editorial policy for a tenant (starts in sandbox mode).

    Requires X-Aion-Actor-Reason header (enforced by middleware for console_proxy callers).
    """
    catalog = _get_catalog()
    policy = next((p for p in catalog if p.id == policy_id), None)
    if policy is None:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found in collective catalog")

    from aion.config import get_settings
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    # Check if already installed
    existing_status = await _get_install_status(tenant, policy_id)
    if existing_status:
        return {
            "policy_id": policy_id,
            "tenant": tenant,
            "status": existing_status,
            "note": f"Already installed with status '{existing_status}'.",
        }

    install = InstalledCollectivePolicy(
        policy_id=policy_id,
        tenant=tenant,
        status="sandbox",
        installed_at=time.time(),
        version=policy.provenance.version,
    )
    await _write_install(install)

    logger.info(
        "Collective policy installed: policy=%s tenant=%s version=%s",
        policy_id, tenant, policy.provenance.version,
    )

    return {
        "policy_id": policy_id,
        "tenant": tenant,
        "status": "sandbox",
        "version": policy.provenance.version,
        "note": "Policy registered in sandbox status. This is administrative lifecycle tracking — runtime enforcement is not yet active.",
    }


@router.put("/v1/collective/policies/{policy_id}/promote", tags=["Collective"])
async def promote_collective_policy(policy_id: str, request: Request):
    """Promote a policy: sandbox → shadow → production.

    Requires X-Aion-Actor-Reason header (enforced by middleware for console_proxy callers).
    """
    from aion.config import get_settings
    settings = get_settings()
    tenant = request.headers.get(settings.tenant_header, settings.default_tenant)

    existing_status = await _get_install_status(tenant, policy_id)
    if not existing_status:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' is not installed for tenant '{tenant}'")
    if existing_status == "production":
        return {"policy_id": policy_id, "tenant": tenant, "status": "production", "note": "Already in production."}

    next_status = "shadow" if existing_status == "sandbox" else "production"

    # Read existing install record and update status
    try:
        from aion.middleware import _redis_client, _redis_available
        key = _install_key(tenant, policy_id)
        if _redis_available and _redis_client:
            raw = await _redis_client.get(key)
            if raw:
                data = json.loads(raw)
                data["status"] = next_status
                await _redis_client.set(key, json.dumps(data), ex=31_536_000)
    except Exception:
        logger.debug("Failed to update install status in Redis", exc_info=True)

    logger.info(
        "Collective policy promoted: policy=%s tenant=%s %s→%s",
        policy_id, tenant, existing_status, next_status,
    )

    return {
        "policy_id": policy_id,
        "tenant": tenant,
        "previous_status": existing_status,
        "status": next_status,
        "note": f"Policy status updated to '{next_status}'. Administrative lifecycle tracking only — runtime enforcement is not yet active.",
    }


@router.get("/v1/collective/installed/{tenant}", tags=["Collective"])
async def get_installed_policies(tenant: str):
    """List all Collective policies installed by a tenant with their current status."""
    installs = await _get_all_installs(tenant)

    # Enrich with policy metadata from catalog
    catalog = {p.id: p for p in _get_catalog()}
    result = []
    for install in installs:
        policy = catalog.get(install.policy_id)
        result.append({
            "policy_id": install.policy_id,
            "name": policy.name if policy else install.policy_id,
            "version": install.version,
            "status": install.status,
            "installed_at": install.installed_at,
            "sectors": policy.sectors if policy else [],
        })

    # Sort by installed_at descending
    result.sort(key=lambda x: x["installed_at"], reverse=True)

    return {
        "tenant": tenant,
        "installed": result,
        "count": len(result),
    }
