"""Marketplace data models."""

from __future__ import annotations

import time
from typing import Optional

from pydantic import BaseModel, Field


class MarketplacePolicy(BaseModel):
    id: str
    name: str
    description: str
    author_tenant: str
    version: str = "1.0.0"
    category: str  # "jailbreak" | "pii" | "compliance" | "domain" | "custom"
    tags: list[str] = []
    content: str   # YAML policy definition (same format as policies.yaml)
    test_cases: list[dict] = []
    price_usd: float = 0.0   # 0 = community (free), >0 = premium
    downloads: int = 0
    rating: float = 0.0
    rating_count: int = 0
    published_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    is_verified: bool = False  # verified by AION team


class PolicyInstallation(BaseModel):
    policy_id: str
    tenant: str
    installed_at: float = Field(default_factory=time.time)
    shadow_mode: bool = True   # start in shadow mode for evaluation
    promoted_at: Optional[float] = None  # when promoted from shadow to active


class PolicyRating(BaseModel):
    policy_id: str
    tenant: str
    rating: int  # 1-5
    comment: str = ""
    rated_at: float = Field(default_factory=time.time)
