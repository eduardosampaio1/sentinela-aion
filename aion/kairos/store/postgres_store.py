"""KairosStore — Postgres backend (enterprise persistent store).

Source of truth for enterprise deployments.
Runs on the customer's local Postgres — NOT Supabase.

Requires asyncpg:
    pip install asyncpg

Set KAIROS_POSTGRES_DSN=postgresql://user:pass@localhost:5432/aion_kairos
and KAIROS_STORAGE_MODE=postgres.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from aion.kairos.models import (
    LifecycleEvent,
    PolicyCandidate,
    PolicyCandidateStatus,
    ShadowRun,
)

logger = logging.getLogger("aion.kairos.store.postgres")


def _load_json(value: Any) -> dict:
    """Deserialize a jsonb value that may be a Python dict (asyncpg decoded) or a str."""
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value  # type: ignore[return-value]
    return json.loads(value)


class PostgresKairosStore:
    """Postgres-backed KAIROS store. Persistent source of truth for enterprise."""

    def __init__(self, dsn: Optional[str]) -> None:
        if not dsn:
            raise ValueError(
                "KAIROS_POSTGRES_DSN must be set when KAIROS_STORAGE_MODE=postgres. "
                "Example: postgresql://user:pass@localhost:5432/aion_kairos"
            )
        self._dsn = dsn
        self._pool = None
        self._lock = asyncio.Lock()

    async def _get_pool(self):
        if self._pool is not None:
            return self._pool
        async with self._lock:
            if self._pool is not None:  # double-checked — another coroutine may have won
                return self._pool
            try:
                import asyncpg  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "asyncpg is required for KAIROS_STORAGE_MODE=postgres. "
                    "Install it: pip install asyncpg"
                ) from exc
            try:
                self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
            except Exception as exc:
                raise RuntimeError(
                    f"KAIROS: Postgres pool creation failed ({type(exc).__name__}): {exc}"
                ) from exc
        return self._pool

    # ── PolicyCandidate ───────────────────────────────────────────────────────

    async def save_candidate(self, candidate: PolicyCandidate) -> None:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO kairos_policy_candidates
                        (id, tenant_id, template_id, status, type, payload, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        payload = EXCLUDED.payload,
                        updated_at = EXCLUDED.updated_at
                    """,
                    candidate.id,
                    candidate.tenant_id,
                    candidate.template_id,
                    candidate.status.value,
                    candidate.type,
                    candidate.model_dump_json(),
                    candidate.created_at,
                    candidate.updated_at,
                )
        except RuntimeError:
            logger.error("Postgres: store unavailable for save_candidate %s", candidate.id, exc_info=True)
        except Exception:
            logger.debug("Postgres: failed to save candidate %s", candidate.id, exc_info=True)

    async def get_candidate(
        self, tenant_id: str, candidate_id: str
    ) -> Optional[PolicyCandidate]:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT payload FROM kairos_policy_candidates WHERE id=$1 AND tenant_id=$2",
                    candidate_id,
                    tenant_id,
                )
                if row:
                    return PolicyCandidate.model_validate_json(row["payload"])
        except RuntimeError:
            logger.error("Postgres: store unavailable for get_candidate %s", candidate_id, exc_info=True)
        except Exception:
            logger.debug("Postgres: failed to get candidate %s", candidate_id, exc_info=True)
        return None

    async def list_candidates(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        policy_type: Optional[str] = None,
    ) -> list[PolicyCandidate]:
        try:
            pool = await self._get_pool()
            query = "SELECT payload FROM kairos_policy_candidates WHERE tenant_id=$1"
            params: list = [tenant_id]
            if status:
                params.append(status)
                query += f" AND status=${len(params)}"
            if policy_type:
                params.append(policy_type)
                query += f" AND type=${len(params)}"
            query += " ORDER BY created_at DESC"
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            results = []
            for row in rows:
                try:
                    results.append(PolicyCandidate.model_validate_json(row["payload"]))
                except Exception:
                    pass
            return results
        except RuntimeError:
            logger.error("Postgres: store unavailable for list_candidates %s", tenant_id, exc_info=True)
        except Exception:
            logger.debug("Postgres: failed to list candidates for %s", tenant_id, exc_info=True)
        return []

    # ── LifecycleEvent ────────────────────────────────────────────────────────

    async def save_lifecycle_event(self, event: LifecycleEvent) -> None:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO kairos_lifecycle_events
                        (id, candidate_id, tenant_id, from_status, to_status,
                         actor_type, actor_id, reason, metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    event.id,
                    event.candidate_id,
                    event.tenant_id,
                    event.from_status,
                    event.to_status,
                    event.actor_type.value,
                    event.actor_id,
                    event.reason,
                    json.dumps(event.metadata),
                    event.created_at,
                )
        except RuntimeError:
            logger.error("Postgres: store unavailable for save_lifecycle_event %s", event.id, exc_info=True)
        except Exception:
            logger.debug("Postgres: failed to save lifecycle event %s", event.id, exc_info=True)

    async def get_lifecycle_events(self, candidate_id: str) -> list[LifecycleEvent]:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM kairos_lifecycle_events WHERE candidate_id=$1 ORDER BY created_at",
                    candidate_id,
                )
            results = []
            for row in rows:
                try:
                    results.append(LifecycleEvent(
                        id=row["id"],
                        candidate_id=row["candidate_id"],
                        tenant_id=row["tenant_id"],
                        from_status=row["from_status"],
                        to_status=row["to_status"],
                        actor_type=row["actor_type"],
                        actor_id=row["actor_id"],
                        reason=row["reason"],
                        metadata=_load_json(row["metadata"]),
                        created_at=str(row["created_at"]),
                    ))
                except Exception:
                    pass
            return results
        except RuntimeError:
            logger.error("Postgres: store unavailable for get_lifecycle_events %s", candidate_id, exc_info=True)
        except Exception:
            logger.debug("Postgres: failed to get lifecycle events for %s", candidate_id, exc_info=True)
        return []

    # ── ShadowRun ─────────────────────────────────────────────────────────────

    async def save_shadow_run(self, run: ShadowRun) -> None:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO kairos_shadow_runs
                        (id, candidate_id, tenant_id, status, observations_count,
                         matched_count, fallback_count, started_at, completed_at, summary)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        observations_count = EXCLUDED.observations_count,
                        matched_count = EXCLUDED.matched_count,
                        fallback_count = EXCLUDED.fallback_count,
                        completed_at = EXCLUDED.completed_at,
                        summary = EXCLUDED.summary
                    """,
                    run.id,
                    run.candidate_id,
                    run.tenant_id,
                    run.status.value,
                    run.observations_count,
                    run.matched_count,
                    run.fallback_count,
                    run.started_at,
                    run.completed_at,
                    json.dumps(run.summary) if run.summary is not None else None,
                )
        except RuntimeError:
            logger.error("Postgres: store unavailable for save_shadow_run %s", run.id, exc_info=True)
        except Exception:
            logger.debug("Postgres: failed to save shadow run %s", run.id, exc_info=True)

    async def get_shadow_run(self, run_id: str) -> Optional[ShadowRun]:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM kairos_shadow_runs WHERE id=$1", run_id
                )
            if row:
                return ShadowRun(
                    id=row["id"],
                    candidate_id=row["candidate_id"],
                    tenant_id=row["tenant_id"],
                    status=row["status"],
                    observations_count=row["observations_count"],
                    matched_count=row["matched_count"],
                    fallback_count=row["fallback_count"],
                    started_at=str(row["started_at"]),
                    completed_at=str(row["completed_at"]) if row["completed_at"] else None,
                    summary=_load_json(row["summary"]) if row["summary"] is not None else None,
                )
        except RuntimeError:
            logger.error("Postgres: store unavailable for get_shadow_run %s", run_id, exc_info=True)
        except Exception:
            logger.debug("Postgres: failed to get shadow run %s", run_id, exc_info=True)
        return None

    async def increment_shadow_counters(
        self,
        run_id: str,
        matched: int = 0,
        fallback: int = 0,
        observations: int = 1,
    ) -> None:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE kairos_shadow_runs
                    SET observations_count = observations_count + $1,
                        matched_count = matched_count + $2,
                        fallback_count = fallback_count + $3
                    WHERE id = $4
                    """,
                    observations,
                    matched,
                    fallback,
                    run_id,
                )
        except RuntimeError:
            logger.error("Postgres: store unavailable for increment_shadow_counters %s", run_id, exc_info=True)
        except Exception:
            logger.debug("Postgres: failed to increment shadow counters for %s", run_id, exc_info=True)

    async def list_shadow_running_candidates(
        self, tenant_id: Optional[str] = None
    ) -> list[PolicyCandidate]:
        try:
            pool = await self._get_pool()
            if tenant_id:
                query = (
                    "SELECT payload FROM kairos_policy_candidates "
                    "WHERE tenant_id=$1 AND status=$2 ORDER BY created_at DESC"
                )
                params: list = [tenant_id, PolicyCandidateStatus.SHADOW_RUNNING.value]
            else:
                query = (
                    "SELECT payload FROM kairos_policy_candidates "
                    "WHERE status=$1 ORDER BY created_at DESC"
                )
                params = [PolicyCandidateStatus.SHADOW_RUNNING.value]
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            results = []
            for row in rows:
                try:
                    results.append(PolicyCandidate.model_validate_json(row["payload"]))
                except Exception:
                    pass
            return results
        except RuntimeError:
            logger.error("Postgres: store unavailable for list_shadow_running_candidates", exc_info=True)
        except Exception:
            logger.debug("Postgres: failed to list shadow_running candidates", exc_info=True)
        return []
