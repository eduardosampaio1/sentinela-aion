"""Daily economics aggregation job.

Reads decision rows from Supabase (aion_decisions) and upserts daily totals
into aion_economics_daily.  Runs as a background asyncio task in main.py,
triggered every AION_ECONOMICS_SWEEP_INTERVAL_SECONDS (default 14400 = 4 h).

Why 4 h and not midnight?  The "today" row must be available in near-real-time
so the status-page spend trend chart shows today's partial data, not only
yesterday's final numbers.

Fail-open contract:
  - Any Supabase error is swallowed; the job retries on the next sweep.
  - If Supabase is not configured the job is a no-op.
  - The pipeline is never blocked by this job.

aion_economics_daily schema (see migrations/supabase/001_aion_core_tables.sql):
  id                TEXT PRIMARY KEY  -- '{tenant}:{date}'
  tenant            TEXT
  date              DATE
  total_requests    INTEGER
  total_cost_usd    NUMERIC
  total_savings_usd NUMERIC
  bypass_count      INTEGER
  block_count       INTEGER
  tokens_saved      INTEGER
  by_model          JSONB             -- {"gpt-4o": {"requests": N, "cost_usd": X}}
  updated_at        TIMESTAMPTZ
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger("aion.economics_daily_job")

# How many days back to (re-)aggregate.
# We re-run the last 3 days so late-arriving rows (clock skew, retries)
# are folded in without requiring a manual backfill.
_LOOKBACK_DAYS = 3

# Maximum rows to fetch per pagination page from Supabase.
_PAGE_SIZE = 1000


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_supabase_enabled() -> bool:
    return bool(
        os.environ.get("AION_SUPABASE_URL", "").strip()
        and os.environ.get("AION_SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )


def _supabase_headers() -> dict[str, str]:
    key = os.environ.get("AION_SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _base_url() -> str:
    return os.environ.get("AION_SUPABASE_URL", "").rstrip("/") + "/rest/v1"


# ── Fetch decisions with pagination ──────────────────────────────────────────

async def _fetch_decisions_for_date(
    client: Any,  # httpx.AsyncClient
    tenant: str,
    target_date: date,
) -> list[dict]:
    """Fetch all aion_decisions rows for a tenant on a given date (paginated)."""
    day_start = datetime(target_date.year, target_date.month, target_date.day,
                         0, 0, 0, tzinfo=timezone.utc).isoformat()
    next_day = date(target_date.year, target_date.month, target_date.day)
    from datetime import timedelta
    day_end = datetime.combine(next_day + timedelta(days=1),
                               datetime.min.time()).replace(tzinfo=timezone.utc).isoformat()

    rows: list[dict] = []
    offset = 0

    while True:
        params = {
            "select": "decision,model_used,cost_actual,cost_default,tokens_saved,cache_hit",
            "tenant": f"eq.{tenant}",
            "created_at": f"gte.{day_start}",
            "created_at": f"lt.{day_end}",  # noqa: F601 — intentional duplicate key for params
            "order": "created_at.asc",
            "limit": str(_PAGE_SIZE),
            "offset": str(offset),
        }
        # Build query string manually to allow duplicate keys
        qs_parts = [
            f"select=decision,model_used,cost_actual,cost_default,tokens_saved,cache_hit",
            f"tenant=eq.{tenant}",
            f"created_at=gte.{day_start}",
            f"created_at=lt.{day_end}",
            f"order=created_at.asc",
            f"limit={_PAGE_SIZE}",
            f"offset={offset}",
        ]
        url = f"{_base_url()}/aion_decisions?{'&'.join(qs_parts)}"

        resp = await client.get(url, headers=_supabase_headers())
        if resp.status_code not in (200, 206):
            logger.debug(
                "economics_daily_job: failed to fetch decisions %s %s",
                resp.status_code, resp.text[:200],
            )
            break

        page = resp.json()
        if not isinstance(page, list):
            break
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break  # last page
        offset += _PAGE_SIZE

    return rows


# ── Aggregate a page of rows ──────────────────────────────────────────────────

def _aggregate(rows: list[dict]) -> dict:
    """Aggregate a list of aion_decisions rows into daily metrics."""
    total_requests = len(rows)
    total_cost = 0.0
    total_savings = 0.0
    bypass_count = 0
    block_count = 0
    tokens_saved_total = 0
    by_model: dict[str, dict] = defaultdict(lambda: {"requests": 0, "cost_usd": 0.0})

    for row in rows:
        decision = (row.get("decision") or "").lower()
        cost_actual = float(row.get("cost_actual") or 0.0)
        cost_default = float(row.get("cost_default") or 0.0)
        tokens_sv = int(row.get("tokens_saved") or 0)
        model = (row.get("model_used") or "unknown").strip() or "unknown"

        total_cost += cost_actual
        total_savings += max(0.0, cost_default - cost_actual)
        tokens_saved_total += tokens_sv

        if decision in ("bypass",):
            bypass_count += 1
        elif decision in ("block",):
            block_count += 1

        by_model[model]["requests"] += 1
        by_model[model]["cost_usd"] = round(by_model[model]["cost_usd"] + cost_actual, 8)

    # Round for storage
    return {
        "total_requests": total_requests,
        "total_cost_usd": round(total_cost, 6),
        "total_savings_usd": round(total_savings, 6),
        "bypass_count": bypass_count,
        "block_count": block_count,
        "tokens_saved": tokens_saved_total,
        "by_model": {
            m: {"requests": v["requests"], "cost_usd": round(v["cost_usd"], 6)}
            for m, v in by_model.items()
        },
    }


# ── Upsert daily row ──────────────────────────────────────────────────────────

async def _upsert_daily_row(
    client: Any,
    tenant: str,
    target_date: date,
    metrics: dict,
) -> None:
    """Upsert one row into aion_economics_daily."""
    row = {
        "id": f"{tenant}:{target_date.isoformat()}",
        "tenant": tenant,
        "date": target_date.isoformat(),
        "total_requests": metrics["total_requests"],
        "total_cost_usd": metrics["total_cost_usd"],
        "total_savings_usd": metrics["total_savings_usd"],
        "bypass_count": metrics["bypass_count"],
        "block_count": metrics["block_count"],
        "tokens_saved": metrics["tokens_saved"],
        "by_model": metrics["by_model"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    url = f"{_base_url()}/aion_economics_daily"
    headers = {
        **_supabase_headers(),
        "Prefer": "resolution=merge-duplicates",  # upsert via ON CONFLICT DO UPDATE
    }
    resp = await client.post(url, json=row, headers=headers)
    if resp.status_code not in (200, 201, 204):
        logger.debug(
            "economics_daily_job: upsert failed %s %s",
            resp.status_code, resp.text[:200],
        )


# ── Tenant discovery ──────────────────────────────────────────────────────────

async def _discover_tenants(client: Any, since_date: date) -> list[str]:
    """Get all distinct tenants that had decisions since `since_date`.

    Paginated so that lookback windows with more than _PAGE_SIZE rows never
    silently truncate the tenant list.  Each page fetches only the `tenant`
    column, so pages are cheap even on large tables.

    Early-exit optimisation: if a full page adds zero new tenants to the
    accumulated set, further pages are guaranteed to contain only already-known
    tenants (tenants are sparse relative to rows), so we stop early.
    """
    cutoff = datetime.combine(since_date, datetime.min.time()).replace(
        tzinfo=timezone.utc
    ).isoformat()

    tenants: set[str] = set()
    offset = 0

    while True:
        url = (
            f"{_base_url()}/aion_decisions"
            f"?select=tenant"
            f"&created_at=gte.{cutoff}"
            f"&order=created_at.asc"
            f"&limit={_PAGE_SIZE}"
            f"&offset={offset}"
        )
        resp = await client.get(url, headers=_supabase_headers())
        if resp.status_code != 200:
            logger.debug(
                "economics_daily_job: _discover_tenants page failed %s",
                resp.status_code,
            )
            break

        page = resp.json()
        if not isinstance(page, list):
            break

        before = len(tenants)
        for r in page:
            t = r.get("tenant")
            if t:
                tenants.add(t)

        if len(page) < _PAGE_SIZE:
            break  # last page — no more rows

        if len(tenants) == before:
            # Full page, but zero new tenants found: all remaining rows belong
            # to tenants already in the set.  Stop early.
            break

        offset += _PAGE_SIZE

    return list(tenants)


# ── Startup table probe ───────────────────────────────────────────────────────

async def probe_supabase_tables() -> None:
    """Warn at startup if aion_economics_daily table doesn't exist in Supabase.

    Called once from main.py lifespan.  Logs an actionable WARNING so operators
    know immediately that the migration must be applied — rather than discovering
    it later via a buried debug log inside the sweep.

    Fail-open: any network error is silently swallowed.
    """
    if not _is_supabase_enabled():
        return

    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = f"{_base_url()}/aion_economics_daily?limit=0&select=id"
            resp = await client.get(url, headers=_supabase_headers())
            if resp.status_code == 404:
                logger.warning(
                    "economics_daily_job: aion_economics_daily table NOT FOUND in Supabase. "
                    "Apply the migration before deploy: "
                    "run migrations/supabase/001_aion_core_tables.sql in the Supabase SQL editor. "
                    "Economics daily sweep will produce errors until the table is created."
                )
            elif resp.status_code not in (200, 206):
                logger.warning(
                    "economics_daily_job: aion_economics_daily probe returned HTTP %s — "
                    "check Supabase credentials and table permissions.",
                    resp.status_code,
                )
            else:
                logger.debug("economics_daily_job: aion_economics_daily table OK")
    except Exception as exc:
        logger.debug("economics_daily_job: Supabase probe failed (non-critical): %s", exc)


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_economics_daily_sweep() -> dict:
    """Aggregate the last LOOKBACK_DAYS days and upsert into aion_economics_daily.

    Returns a summary dict: {"days_processed": N, "tenants": [...], "rows_written": N}
    """
    if not _is_supabase_enabled():
        return {"skipped": True, "reason": "supabase_not_configured"}

    import httpx
    from datetime import timedelta

    summary: dict = {"days_processed": 0, "tenants": [], "rows_written": 0}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            today = date.today()
            lookback_start = today - timedelta(days=_LOOKBACK_DAYS - 1)

            # Discover all tenants active in the lookback window
            tenants = await _discover_tenants(client, lookback_start)
            if not tenants:
                logger.debug("economics_daily_job: no tenants found, nothing to aggregate")
                return summary

            summary["tenants"] = tenants

            for tenant in tenants:
                for day_offset in range(_LOOKBACK_DAYS):
                    target_date = today - timedelta(days=day_offset)
                    rows = await _fetch_decisions_for_date(client, tenant, target_date)
                    if not rows:
                        continue
                    metrics = _aggregate(rows)
                    await _upsert_daily_row(client, tenant, target_date, metrics)
                    summary["rows_written"] += 1
                    summary["days_processed"] += 1
                    logger.debug(
                        "economics_daily_job: upserted %s / %s — %d requests, $%.4f",
                        tenant, target_date, metrics["total_requests"],
                        metrics["total_cost_usd"],
                    )

    except Exception as exc:
        logger.warning("economics_daily_job: sweep failed (non-fatal): %s", exc, exc_info=True)

    if summary.get("rows_written"):
        logger.info(
            "economics_daily_job: wrote %d rows for %d tenant(s)",
            summary["rows_written"],
            len(summary.get("tenants", [])),
        )
    return summary


# ── Read path (for the /v1/economics/daily endpoint) ─────────────────────────

async def fetch_daily_economics(tenant: str, days: int = 30) -> list[dict]:
    """Read aggregated daily economics from aion_economics_daily.

    Returns up to `days` rows sorted by date descending.
    Returns empty list when Supabase is not configured or on error.
    """
    if not _is_supabase_enabled():
        return []

    import httpx
    from datetime import timedelta

    cutoff = (date.today() - timedelta(days=days - 1)).isoformat()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = (
                f"{_base_url()}/aion_economics_daily"
                f"?tenant=eq.{tenant}"
                f"&date=gte.{cutoff}"
                f"&order=date.asc"
                f"&limit={days + 5}"  # small buffer for safety
            )
            resp = await client.get(url, headers=_supabase_headers())
            if resp.status_code != 200:
                logger.debug(
                    "fetch_daily_economics: query failed %s", resp.status_code
                )
                return []
            rows = resp.json()
            return rows if isinstance(rows, list) else []
    except Exception as exc:
        logger.debug("fetch_daily_economics: error: %s", exc)
        return []
