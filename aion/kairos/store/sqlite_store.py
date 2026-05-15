"""KairosStore — SQLite backend (POC/demo/offline mode).

Source of truth for development and demo environments.
Uses Python built-in sqlite3 via asyncio.to_thread (no aiosqlite dependency).
Auto-applies migrations on first use.

For enterprise production, prefer storage_mode=postgres.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from aion.kairos.models import (
    LifecycleEvent,
    PolicyCandidate,
    PolicyCandidateStatus,
    ShadowRun,
)

logger = logging.getLogger("aion.kairos.store.sqlite")

_DDL = """
CREATE TABLE IF NOT EXISTS kairos_policy_candidates (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    template_id TEXT,
    status TEXT NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kpc_tenant_status
    ON kairos_policy_candidates (tenant_id, status);

CREATE TABLE IF NOT EXISTS kairos_lifecycle_events (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    reason TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kle_candidate
    ON kairos_lifecycle_events (candidate_id);
CREATE INDEX IF NOT EXISTS idx_kle_tenant_ts
    ON kairos_lifecycle_events (tenant_id, created_at);

CREATE TABLE IF NOT EXISTS kairos_shadow_runs (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL,
    observations_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    fallback_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    summary TEXT
);
CREATE INDEX IF NOT EXISTS idx_ksr_candidate
    ON kairos_shadow_runs (candidate_id);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_DDL)
    conn.commit()
    return conn


class SQLiteKairosStore:
    """SQLite-backed KAIROS store. Source of truth for demo/dev mode."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _connect(self._db_path)
        return self._conn

    async def _run(self, fn):
        async with self._lock:
            return await asyncio.to_thread(fn)

    # ── PolicyCandidate ───────────────────────────────────────────────────────

    async def save_candidate(self, candidate: PolicyCandidate) -> None:
        def _write():
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO kairos_policy_candidates
                    (id, tenant_id, template_id, status, type, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    candidate.id,
                    candidate.tenant_id,
                    candidate.template_id,
                    candidate.status.value,
                    candidate.type,
                    candidate.model_dump_json(),
                    candidate.created_at,
                    candidate.updated_at,
                ),
            )
            conn.commit()

        try:
            await self._run(_write)
        except Exception:
            logger.debug("SQLite: failed to save candidate %s", candidate.id, exc_info=True)

    async def get_candidate(
        self, tenant_id: str, candidate_id: str
    ) -> Optional[PolicyCandidate]:
        def _read():
            conn = self._get_conn()
            row = conn.execute(
                "SELECT payload FROM kairos_policy_candidates WHERE id=? AND tenant_id=?",
                (candidate_id, tenant_id),
            ).fetchone()
            return row["payload"] if row else None

        try:
            raw = await self._run(_read)
            if raw:
                return PolicyCandidate.model_validate_json(raw)
        except Exception:
            logger.debug("SQLite: failed to get candidate %s", candidate_id, exc_info=True)
        return None

    async def list_candidates(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        policy_type: Optional[str] = None,
    ) -> list[PolicyCandidate]:
        def _read():
            conn = self._get_conn()
            query = "SELECT payload FROM kairos_policy_candidates WHERE tenant_id=?"
            params: list = [tenant_id]
            if status:
                query += " AND status=?"
                params.append(status)
            if policy_type:
                query += " AND type=?"
                params.append(policy_type)
            query += " ORDER BY created_at DESC"
            return [row["payload"] for row in conn.execute(query, params).fetchall()]

        try:
            raws = await self._run(_read)
            results = []
            for raw in raws:
                try:
                    results.append(PolicyCandidate.model_validate_json(raw))
                except Exception:
                    pass
            return results
        except Exception:
            logger.debug("SQLite: failed to list candidates for %s", tenant_id, exc_info=True)
            return []

    # ── LifecycleEvent ────────────────────────────────────────────────────────

    async def save_lifecycle_event(self, event: LifecycleEvent) -> None:
        def _write():
            conn = self._get_conn()
            conn.execute(
                """
                INSERT OR IGNORE INTO kairos_lifecycle_events
                    (id, candidate_id, tenant_id, from_status, to_status,
                     actor_type, actor_id, reason, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
                ),
            )
            conn.commit()

        try:
            await self._run(_write)
        except Exception:
            logger.debug("SQLite: failed to save lifecycle event %s", event.id, exc_info=True)

    async def get_lifecycle_events(self, candidate_id: str) -> list[LifecycleEvent]:
        def _read():
            conn = self._get_conn()
            return conn.execute(
                "SELECT * FROM kairos_lifecycle_events WHERE candidate_id=? ORDER BY created_at",
                (candidate_id,),
            ).fetchall()

        try:
            rows = await self._run(_read)
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
                        metadata=json.loads(row["metadata"] or "{}"),
                        created_at=row["created_at"],
                    ))
                except Exception:
                    pass
            return results
        except Exception:
            logger.debug("SQLite: failed to get lifecycle events for %s", candidate_id, exc_info=True)
            return []

    # ── ShadowRun ─────────────────────────────────────────────────────────────

    async def save_shadow_run(self, run: ShadowRun) -> None:
        def _write():
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO kairos_shadow_runs
                    (id, candidate_id, tenant_id, status, observations_count,
                     matched_count, fallback_count, started_at, completed_at, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    observations_count = excluded.observations_count,
                    matched_count = excluded.matched_count,
                    fallback_count = excluded.fallback_count,
                    completed_at = excluded.completed_at,
                    summary = excluded.summary
                """,
                (
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
                ),
            )
            conn.commit()

        try:
            await self._run(_write)
        except Exception:
            logger.debug("SQLite: failed to save shadow run %s", run.id, exc_info=True)

    async def get_shadow_run(self, run_id: str) -> Optional[ShadowRun]:
        def _read():
            conn = self._get_conn()
            return conn.execute(
                "SELECT * FROM kairos_shadow_runs WHERE id=?", (run_id,)
            ).fetchone()

        try:
            row = await self._run(_read)
            if row:
                return ShadowRun(
                    id=row["id"],
                    candidate_id=row["candidate_id"],
                    tenant_id=row["tenant_id"],
                    status=row["status"],
                    observations_count=row["observations_count"],
                    matched_count=row["matched_count"],
                    fallback_count=row["fallback_count"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    summary=json.loads(row["summary"]) if row["summary"] else None,
                )
        except Exception:
            logger.debug("SQLite: failed to get shadow run %s", run_id, exc_info=True)
        return None

    async def increment_shadow_counters(
        self,
        run_id: str,
        matched: int = 0,
        fallback: int = 0,
        observations: int = 1,
    ) -> None:
        def _update():
            conn = self._get_conn()
            conn.execute(
                """
                UPDATE kairos_shadow_runs
                SET observations_count = observations_count + ?,
                    matched_count = matched_count + ?,
                    fallback_count = fallback_count + ?
                WHERE id = ?
                """,
                (observations, matched, fallback, run_id),
            )
            conn.commit()

        try:
            await self._run(_update)
        except Exception:
            logger.debug("SQLite: failed to increment shadow counters for %s", run_id, exc_info=True)

    async def list_shadow_running_candidates(
        self, tenant_id: Optional[str] = None
    ) -> list[PolicyCandidate]:
        def _read():
            conn = self._get_conn()
            if tenant_id:
                return conn.execute(
                    "SELECT payload FROM kairos_policy_candidates WHERE tenant_id=? AND status=?",
                    (tenant_id, PolicyCandidateStatus.SHADOW_RUNNING.value),
                ).fetchall()
            return conn.execute(
                "SELECT payload FROM kairos_policy_candidates WHERE status=?",
                (PolicyCandidateStatus.SHADOW_RUNNING.value,),
            ).fetchall()

        try:
            rows = await self._run(_read)
            results = []
            for row in rows:
                try:
                    results.append(PolicyCandidate.model_validate_json(row["payload"]))
                except Exception:
                    pass
            return results
        except Exception:
            logger.debug("SQLite: failed to list shadow_running candidates", exc_info=True)
            return []
