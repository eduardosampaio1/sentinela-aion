"""Gain Report router — GET /v1/nemos/gain."""

from __future__ import annotations

import datetime
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger("aion")

router = APIRouter()

_DEFAULT_WINDOW_DAYS = 30


def _parse_date(value: str, param_name: str) -> datetime.datetime:
    """Parse ISO date or datetime string; raises HTTPException 400 on failure.

    Always returns a UTC-aware datetime so that .timestamp() is unambiguous
    regardless of the server's local timezone.
    """
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.datetime.strptime(value, fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    raise HTTPException(
        status_code=400,
        detail=f"Invalid date format for '{param_name}': {value!r}. "
               "Expected ISO 8601 date (YYYY-MM-DD) or datetime (YYYY-MM-DDTHH:MM:SS).",
    )


@router.get("/v1/nemos/gain", tags=["Reports"])
async def get_gain_report(
    request: Request,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    group_by: Optional[str] = Query(None),       # reserved — not implemented in v0
    workspace_id: Optional[str] = Query(None),   # supplementary only; does not override tenant
    project_id: Optional[str] = Query(None),
    environment_id: Optional[str] = Query(None),
):
    """Return AION Gain Report for a tenant over a time window.

    Tenant is resolved from the X-Aion-Tenant header (set by AionSecurityMiddleware).
    The `workspace_id` query param is ignored for tenant resolution.

    Parameters
    ----------
    from : ISO date or datetime (inclusive). Defaults to 30 days ago.
    to   : ISO date or datetime (inclusive). Defaults to now.
    group_by : reserved — accepted but not implemented in v0.
    """
    # Tenant from authenticated header only
    tenant = request.headers.get("X-Aion-Tenant", "default")

    # Parse time window
    to_dt = (
        _parse_date(to, "to")
        if to
        else datetime.datetime.now(tz=datetime.timezone.utc)
    )
    from_dt = (
        _parse_date(from_, "from")
        if from_
        else to_dt - datetime.timedelta(days=_DEFAULT_WINDOW_DAYS)
    )

    if from_dt > to_dt:
        raise HTTPException(
            status_code=400,
            detail="'from' must be before 'to'.",
        )

    from aion.nemos.gain_report import GainReportBuilder

    report = await GainReportBuilder().build(tenant, from_dt, to_dt)
    result = report.to_dict()

    # group_by is reserved — document in calculation_notes if provided
    if group_by:
        result["calculation_notes"] = result.get("calculation_notes", []) + [
            "group_by parameter is accepted but not implemented in v0; "
            "full breakdowns are always returned."
        ]

    return result
