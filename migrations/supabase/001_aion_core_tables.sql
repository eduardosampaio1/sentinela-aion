-- AION Core Tables — Supabase migration
-- Apply in Supabase SQL editor or via: supabase db push
-- Tables: aion_decisions, aion_audit_events, aion_economics_daily

-- ── aion_decisions ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS aion_decisions (
    id               BIGSERIAL PRIMARY KEY,
    tenant           TEXT NOT NULL,
    request_id       TEXT,
    decision         TEXT NOT NULL,
    model_used       TEXT,
    detected_intent  TEXT,
    complexity_score NUMERIC(5,4),
    risk_category    TEXT,
    tokens_input     INTEGER,
    tokens_output    INTEGER,
    cost_actual      NUMERIC(10,8),
    cost_default     NUMERIC(10,8),
    tokens_saved     INTEGER,
    cost_saved       NUMERIC(10,8),
    pii_detected     BOOLEAN NOT NULL DEFAULT FALSE,
    pii_count        INTEGER NOT NULL DEFAULT 0,
    latency_ms       INTEGER,
    estixe_decision  TEXT,
    nomos_decision   TEXT,
    metis_decision   TEXT,
    cache_hit        BOOLEAN NOT NULL DEFAULT FALSE,
    safe_mode        BOOLEAN NOT NULL DEFAULT FALSE,
    metadata         JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ad_tenant_created
    ON aion_decisions (tenant, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ad_created
    ON aion_decisions (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ad_decision
    ON aion_decisions (tenant, decision);

-- ── aion_audit_events ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS aion_audit_events (
    id           BIGSERIAL PRIMARY KEY,
    tenant       TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    actor        TEXT,
    target       TEXT,
    outcome      TEXT,
    request_id   TEXT,
    event_hash   TEXT,
    prev_hash    TEXT,
    details      JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_aae_tenant_created
    ON aion_audit_events (tenant, created_at DESC);

-- ── aion_economics_daily ──────────────────────────────────────────────────────
-- Daily aggregated economics per tenant.
-- Written by the background economics_daily_job running every 4 hours.
-- Read by GET /v1/economics/daily for the spend trend charts.

CREATE TABLE IF NOT EXISTS aion_economics_daily (
    id                TEXT        PRIMARY KEY,          -- '{tenant}:{date}'
    tenant            TEXT        NOT NULL,
    date              DATE        NOT NULL,
    total_requests    INTEGER     NOT NULL DEFAULT 0,
    total_cost_usd    NUMERIC(12,6) NOT NULL DEFAULT 0,
    total_savings_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    bypass_count      INTEGER     NOT NULL DEFAULT 0,
    block_count       INTEGER     NOT NULL DEFAULT 0,
    tokens_saved      INTEGER     NOT NULL DEFAULT 0,
    -- Per-model breakdown: {"gpt-4o": {"requests": N, "cost_usd": 1.23}, ...}
    by_model          JSONB       NOT NULL DEFAULT '{}',
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ead_tenant_date
    ON aion_economics_daily (tenant, date DESC);

-- Row-Level Security (apply per-tenant access control)
-- Uncomment and adapt when multi-tenant access is required:
-- ALTER TABLE aion_economics_daily ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "tenant_isolation" ON aion_economics_daily
--     USING (tenant = current_setting('app.current_tenant', TRUE));
