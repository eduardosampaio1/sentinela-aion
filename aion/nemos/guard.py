"""ActuationGuard — monitors auto-actuation impact and rolls back if degraded.

Every safe auto-actuation (threshold adjust, compression change, etc.) is
wrapped in a guard. After ``window_requests`` observations, if the monitored
metric worsened beyond ``rollback_threshold``, the actuation is reverted.

After a rollback, a ``cooldown_requests`` period blocks new attempts to
prevent adjust→rollback→adjust loops.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("aion.nemos.guard")


@dataclass
class ActuationGuard:
    """Tracks a single auto-actuation and decides whether to rollback."""

    actuation_type: str          # "threshold_adjust" | "compression_reduce" | etc.
    tenant: str
    module: str                  # "estixe" | "nomos" | "metis"
    param_name: str              # which parameter was changed
    value_before: float          # original value
    value_after: float           # new value (the actuation)
    metric_before: float         # snapshot of monitored metric before change
    applied_at: float = field(default_factory=time.time)
    window_requests: int = 50    # observe this many requests before evaluating
    rollback_threshold: float = 0.10  # 10% degradation triggers rollback
    cooldown_requests: int = 100  # block new attempts after rollback
    requests_observed: int = 0
    metric_sum: float = 0.0
    rolled_back: bool = False
    cooldown_remaining: int = 0

    def observe(self, metric_value: float) -> bool | None:
        """Record an observation. Returns True if rollback triggered, False if kept, None if still observing."""
        if self.rolled_back:
            # In cooldown — count down
            if self.cooldown_remaining > 0:
                self.cooldown_remaining -= 1
            return None

        self.requests_observed += 1
        self.metric_sum += metric_value

        if self.requests_observed < self.window_requests:
            return None  # still observing

        # Evaluate
        metric_after = self.metric_sum / self.requests_observed
        if self.metric_before > 0:
            degradation = (metric_after - self.metric_before) / self.metric_before
        else:
            degradation = 0.0

        if degradation > self.rollback_threshold:
            # Rollback
            self.rolled_back = True
            self.cooldown_remaining = self.cooldown_requests
            logger.warning(
                "ROLLBACK: %s on %s/%s — %s reverted from %.4f to %.4f "
                "(metric degraded %.1f%%, threshold %.1f%%)",
                self.actuation_type, self.tenant, self.module,
                self.param_name, self.value_after, self.value_before,
                degradation * 100, self.rollback_threshold * 100,
            )
            return True

        logger.info(
            "ACTUATION KEPT: %s on %s/%s — %s at %.4f "
            "(metric change %.1f%%, within threshold)",
            self.actuation_type, self.tenant, self.module,
            self.param_name, self.value_after,
            degradation * 100,
        )
        return False

    @property
    def in_cooldown(self) -> bool:
        return self.rolled_back and self.cooldown_remaining > 0

    def to_dict(self) -> dict:
        return {
            "actuation_type": self.actuation_type,
            "tenant": self.tenant,
            "module": self.module,
            "param_name": self.param_name,
            "value_before": self.value_before,
            "value_after": self.value_after,
            "metric_before": self.metric_before,
            "requests_observed": self.requests_observed,
            "rolled_back": self.rolled_back,
            "in_cooldown": self.in_cooldown,
            "cooldown_remaining": self.cooldown_remaining,
        }


class GuardRegistry:
    """Manages active actuation guards per tenant+module."""

    def __init__(self) -> None:
        self._guards: dict[str, ActuationGuard] = {}  # key: "{tenant}:{module}:{param}"

    def register(self, guard: ActuationGuard) -> None:
        key = f"{guard.tenant}:{guard.module}:{guard.param_name}"
        self._guards[key] = guard

    def get(self, tenant: str, module: str, param_name: str) -> ActuationGuard | None:
        return self._guards.get(f"{tenant}:{module}:{param_name}")

    def is_in_cooldown(self, tenant: str, module: str, param_name: str) -> bool:
        guard = self.get(tenant, module, param_name)
        return guard.in_cooldown if guard else False

    def get_rollback_value(self, tenant: str, module: str, param_name: str) -> float | None:
        """If a guard rolled back, return the original value to restore."""
        guard = self.get(tenant, module, param_name)
        if guard and guard.rolled_back:
            return guard.value_before
        return None

    def observe_all(self, tenant: str, module: str, metric_value: float) -> list[ActuationGuard]:
        """Observe a metric for all active guards of a tenant+module. Returns guards that rolled back."""
        rolled_back = []
        prefix = f"{tenant}:{module}:"
        for key, guard in self._guards.items():
            if key.startswith(prefix) and not guard.rolled_back:
                result = guard.observe(metric_value)
                if result is True:
                    rolled_back.append(guard)
        return rolled_back

    def active_guards(self) -> list[dict]:
        return [g.to_dict() for g in self._guards.values()]

    def cleanup_completed(self) -> None:
        """Remove guards that have completed evaluation (kept or cooldown expired)."""
        to_remove = [
            key for key, guard in self._guards.items()
            if (not guard.rolled_back and guard.requests_observed >= guard.window_requests)
            or (guard.rolled_back and guard.cooldown_remaining <= 0)
        ]
        for key in to_remove:
            del self._guards[key]
