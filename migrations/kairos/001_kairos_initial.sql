-- KAIROS V0 — Initial schema migration
-- Postgres standard (runs on customer's local Postgres — NOT Supabase)
-- Apply with: psql $KAIROS_POSTGRES_DSN -f 001_kairos_initial.sql

-- ── PolicyCandidates ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kairos_policy_candidates (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    template_id TEXT,
    status      TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT '',
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kpc_tenant_status
    ON kairos_policy_candidates (tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_kpc_tenant_created
    ON kairos_policy_candidates (tenant_id, created_at DESC);

-- ── LifecycleEvents ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kairos_lifecycle_events (
    id           TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    tenant_id    TEXT NOT NULL,
    from_status  TEXT,
    to_status    TEXT NOT NULL,
    actor_type   TEXT NOT NULL,
    actor_id     TEXT,
    reason       TEXT,
    metadata     JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kle_candidate
    ON kairos_lifecycle_events (candidate_id);

CREATE INDEX IF NOT EXISTS idx_kle_tenant_ts
    ON kairos_lifecycle_events (tenant_id, created_at DESC);

-- ── ShadowRuns ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kairos_shadow_runs (
    id                 TEXT PRIMARY KEY,
    candidate_id       TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    status             TEXT NOT NULL,
    observations_count INTEGER NOT NULL DEFAULT 0,
    matched_count      INTEGER NOT NULL DEFAULT 0,
    fallback_count     INTEGER NOT NULL DEFAULT 0,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at       TIMESTAMPTZ,
    summary            JSONB
);

CREATE INDEX IF NOT EXISTS idx_ksr_candidate
    ON kairos_shadow_runs (candidate_id);

CREATE INDEX IF NOT EXISTS idx_ksr_status
    ON kairos_shadow_runs (status)
    WHERE status = 'running';

-- ── PolicyTemplates ───────────────────────────────────────────────────────────
-- Populated from YAML at boot (read-only at runtime via templates.py).
-- This table is optional — templates.py uses YAML as source of truth.
-- Operators can import templates here for cross-instance sharing.

CREATE TABLE IF NOT EXISTS kairos_policy_templates (
    id         TEXT PRIMARY KEY,
    vertical   TEXT NOT NULL,
    type       TEXT NOT NULL,
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
