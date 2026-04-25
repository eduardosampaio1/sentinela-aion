"""Marketplace router: /v1/marketplace/policies."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, HTTPException

logger = logging.getLogger("aion")

router = APIRouter()


@router.post("/v1/marketplace/policies", tags=["Marketplace"])
async def publish_policy(request: Request):
    """Publish a policy to the marketplace."""
    from aion.marketplace.models import MarketplacePolicy
    from aion.marketplace.store import get_marketplace_store

    body = await request.json()
    tenant = request.headers.get("X-Tenant-ID", "unknown")
    policy = MarketplacePolicy(
        id="",
        name=body.get("name", ""),
        description=body.get("description", ""),
        author_tenant=tenant,
        version=body.get("version", "1.0.0"),
        category=body.get("category", "custom"),
        tags=body.get("tags", []),
        content=body.get("content", ""),
        test_cases=body.get("test_cases", []),
        price_usd=float(body.get("price_usd", 0.0)),
    )
    if not policy.name or not policy.content:
        raise HTTPException(status_code=422, detail="name and content are required")
    published = await get_marketplace_store().publish(policy)
    return {"policy": published.model_dump(), "status": "published"}


@router.get("/v1/marketplace/policies", tags=["Marketplace"])
async def browse_policies(
    category: str = None,
    tag: str = None,
    limit: int = 20,
    offset: int = 0,
):
    """Browse marketplace policies. Sorted by popularity (downloads × rating)."""
    from aion.marketplace.store import get_marketplace_store

    policies = await get_marketplace_store().browse(category=category, tag=tag, limit=limit, offset=offset)
    return {
        "policies": [p.model_dump() for p in policies],
        "count": len(policies),
        "offset": offset,
    }


@router.get("/v1/marketplace/policies/{policy_id}", tags=["Marketplace"])
async def get_policy(policy_id: str):
    """Get details for a specific marketplace policy."""
    from aion.marketplace.store import get_marketplace_store

    policy = await get_marketplace_store().get(policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy.model_dump()


@router.post("/v1/marketplace/policies/{policy_id}/install", tags=["Marketplace"])
async def install_policy(policy_id: str, request: Request):
    """Install a marketplace policy for a tenant."""
    from aion.marketplace.store import get_marketplace_store

    tenant = request.headers.get("X-Tenant-ID", "unknown")
    try:
        body = await request.json()
    except Exception:
        body = {}
    shadow = bool(body.get("shadow_mode", True))

    policy = await get_marketplace_store().get(policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")

    installation = await get_marketplace_store().install(policy_id, tenant, shadow=shadow)
    return {
        "policy_id": policy_id,
        "tenant": tenant,
        "installation": installation.model_dump(),
        "note": "Policy installed in shadow mode — observe metrics before promoting to active." if shadow else "Policy active.",
    }


@router.post("/v1/marketplace/policies/{policy_id}/rate", tags=["Marketplace"])
async def rate_policy(policy_id: str, request: Request):
    """Rate a marketplace policy (1-5 stars)."""
    from aion.marketplace.store import get_marketplace_store

    tenant = request.headers.get("X-Tenant-ID", "unknown")
    body = await request.json()
    rating = int(body.get("rating", 0))
    if not 1 <= rating <= 5:
        raise HTTPException(status_code=422, detail="rating must be between 1 and 5")

    policy = await get_marketplace_store().get(policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")

    await get_marketplace_store().rate(policy_id, tenant, rating, body.get("comment", ""))
    return {"policy_id": policy_id, "tenant": tenant, "rating": rating, "status": "recorded"}
