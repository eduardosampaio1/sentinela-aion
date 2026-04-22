"""Shadow observation tracking for NEMOS.

Accumulates per-tenant, per-category shadow-mode detections.
Used to compute promotion readiness: volume + stability + drift control.
No user content stored — only aggregate confidence statistics.

Variance tracked via Welford's online algorithm (numerically stable, single-pass).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ShadowObservation:
    """Accumulated shadow observations for one tenant+category pair.

    Tracks confidence mean, variance (Welford), and promotion lifecycle.
    All fields are aggregate-only — no user content.
    """

    category: str
    tenant: str
    total_seen: int = 0
    avg_confidence: float = 0.0
    min_confidence: float = 1.0
    max_confidence: float = 0.0
    # Welford's online variance (M2 = sum of squared deviations from running mean)
    _m2: float = 0.0
    first_seen_ts: float = field(default_factory=time.time)
    last_seen_ts: float = field(default_factory=time.time)
    # Promotion lifecycle
    promoted: bool = False
    promoted_at: float = 0.0
    # Cooldown tracking — survives rollback so rapid re-promotion is blocked
    last_promotion_ts: float = 0.0
    # Rollback: last known pre-promotion threshold (None = was using taxonomy default)
    previous_threshold: Optional[float] = None

    # ── Derived properties ──

    @property
    def days_monitored(self) -> float:
        if self.total_seen == 0:
            return 0.0
        return (self.last_seen_ts - self.first_seen_ts) / 86400

    @property
    def confidence_variance(self) -> float:
        """Sample variance (Bessel corrected). 0.0 when n < 2."""
        if self.total_seen < 2:
            return 0.0
        return self._m2 / (self.total_seen - 1)

    @property
    def confidence_std(self) -> float:
        return math.sqrt(self.confidence_variance)

    @property
    def stability_score(self) -> float:
        """Stability in [0, 1]. 1.0 = perfectly stable, 0.0 = std >= 0.30.

        Normalized so that std=0.05 → score≈0.83, std=0.10 → score≈0.67.
        Threshold for promotion: score >= 1 - (max_std / 0.30).
        """
        return max(0.0, 1.0 - (self.confidence_std / 0.30))

    # ── Mutation ──

    def record(self, confidence: float) -> None:
        """Update running statistics using Welford's algorithm."""
        now = time.time()
        if self.total_seen == 0:
            self.first_seen_ts = now
        self.total_seen += 1
        self.last_seen_ts = now
        # Welford update
        delta = confidence - self.avg_confidence
        self.avg_confidence += delta / self.total_seen
        delta2 = confidence - self.avg_confidence
        self._m2 += delta * delta2
        # Range
        self.min_confidence = min(self.min_confidence, confidence)
        self.max_confidence = max(self.max_confidence, confidence)

    # ── Readiness ──

    def is_promotion_ready(self, min_requests: int, min_days: int) -> bool:
        return (
            not self.promoted
            and self.total_seen >= min_requests
            and self.days_monitored >= min_days
        )

    def is_stable_enough(self, max_std: float) -> bool:
        """True when signal variance is below acceptable threshold."""
        if self.total_seen < 2:
            return False
        return self.confidence_std <= max_std

    def cooldown_remaining_days(self, cooldown_days: float) -> float:
        """Days remaining in cooldown period after last promotion. 0.0 = ready."""
        if self.last_promotion_ts == 0.0:
            return 0.0
        elapsed = (time.time() - self.last_promotion_ts) / 86400
        return max(0.0, cooldown_days - elapsed)

    def suggested_threshold(self) -> float:
        """Suggest enforcement threshold slightly below avg confidence.

        Leaves a 5% margin → catches patterns seen during shadow while
        avoiding FP spikes on borderline cases. Clamped to [0.65, 0.92].
        """
        if self.total_seen == 0:
            return 0.75
        return max(0.65, min(0.92, round(self.avg_confidence * 0.95, 3)))

    def promotion_summary(self, min_requests: int, min_days: int) -> dict:
        return {
            "ready_to_promote": self.is_promotion_ready(min_requests, min_days),
            "criteria": {
                "min_requests": min_requests,
                "current_requests": self.total_seen,
                "min_days": min_days,
                "current_days": round(self.days_monitored, 2),
            },
            "suggested_threshold": self.suggested_threshold(),
            "avg_confidence": round(self.avg_confidence, 4),
            "confidence_std": round(self.confidence_std, 4),
            "stability_score": round(self.stability_score, 3),
        }

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "tenant": self.tenant,
            "total_seen": self.total_seen,
            "avg_confidence": round(self.avg_confidence, 6),
            "min_confidence": round(self.min_confidence, 6),
            "max_confidence": round(self.max_confidence, 6),
            "_m2": self._m2,
            "confidence_std": round(self.confidence_std, 6),
            "stability_score": round(self.stability_score, 4),
            "first_seen_ts": self.first_seen_ts,
            "last_seen_ts": self.last_seen_ts,
            "days_monitored": round(self.days_monitored, 4),
            "promoted": self.promoted,
            "promoted_at": self.promoted_at,
            "last_promotion_ts": self.last_promotion_ts,
            "previous_threshold": self.previous_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ShadowObservation":
        obj = cls(
            category=data.get("category", ""),
            tenant=data.get("tenant", ""),
        )
        obj.total_seen = data.get("total_seen", 0)
        obj.avg_confidence = data.get("avg_confidence", 0.0)
        obj.min_confidence = data.get("min_confidence", 1.0)
        obj.max_confidence = data.get("max_confidence", 0.0)
        obj._m2 = data.get("_m2", 0.0)
        obj.first_seen_ts = data.get("first_seen_ts", time.time())
        obj.last_seen_ts = data.get("last_seen_ts", time.time())
        obj.promoted = data.get("promoted", False)
        obj.promoted_at = data.get("promoted_at", 0.0)
        obj.last_promotion_ts = data.get("last_promotion_ts", 0.0)
        obj.previous_threshold = data.get("previous_threshold", None)
        return obj
