"""KairosStore Protocol — abstract interface for all storage backends."""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from aion.kairos.models import LifecycleEvent, PolicyCandidate, ShadowRun


@runtime_checkable
class KairosStore(Protocol):
    """Storage contract for KAIROS operational data.

    All methods are async. Implementations must be safe to call concurrently.
    Errors must be logged and swallowed — never raised to callers (fire-and-forget
    writes) except for explicit read methods that return Optional.
    """

    async def save_candidate(self, candidate: PolicyCandidate) -> None: ...

    async def get_candidate(
        self, tenant_id: str, candidate_id: str
    ) -> Optional[PolicyCandidate]: ...

    async def list_candidates(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        policy_type: Optional[str] = None,
    ) -> list[PolicyCandidate]: ...

    async def save_lifecycle_event(self, event: LifecycleEvent) -> None: ...

    async def get_lifecycle_events(
        self, candidate_id: str
    ) -> list[LifecycleEvent]: ...

    async def save_shadow_run(self, run: ShadowRun) -> None: ...

    async def get_shadow_run(self, run_id: str) -> Optional[ShadowRun]: ...

    async def increment_shadow_counters(
        self,
        run_id: str,
        matched: int = 0,
        fallback: int = 0,
        observations: int = 1,
    ) -> None: ...

    async def list_shadow_running_candidates(
        self, tenant_id: Optional[str] = None
    ) -> list[PolicyCandidate]: ...
