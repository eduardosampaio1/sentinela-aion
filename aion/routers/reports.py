"""Reports router: /v1/reports/{tenant_id}/executive, /v1/reports/{tenant_id}/schedule."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger("aion")

router = APIRouter()


@router.get("/v1/reports/{tenant_id}/executive", tags=["Reports"])
async def get_executive_report(tenant_id: str, format: str = "pdf", days: int = 30):
    """Generate or serve cached executive report for a tenant."""
    import datetime
    from aion.reports.data_builder import build_report_data

    period = datetime.date.today().strftime("%Y-%m")

    if format == "json":
        data = await build_report_data(tenant_id, period_days=days)
        return data

    from aion.reports.scheduler import get_cached_report, cache_report
    cached = await get_cached_report(tenant_id, period)
    if cached:
        from fastapi.responses import Response as FResponse
        return FResponse(content=cached, media_type="application/pdf",
                         headers={"Content-Disposition": f"attachment; filename=aion-report-{tenant_id}-{period}.pdf"})

    data = await build_report_data(tenant_id, period_days=days)
    from aion.reports.pdf_renderer import render_pdf
    pdf_bytes = render_pdf(data)
    await cache_report(tenant_id, period, pdf_bytes)
    from fastapi.responses import Response as FResponse
    return FResponse(content=pdf_bytes, media_type="application/pdf",
                     headers={"Content-Disposition": f"attachment; filename=aion-report-{tenant_id}-{period}.pdf"})


@router.post("/v1/reports/{tenant_id}/schedule", tags=["Reports"])
async def set_report_schedule(tenant_id: str, request: Request):
    """Configure automated report generation for a tenant."""
    import time
    from aion.reports.scheduler import ReportSchedule, save_schedule, get_schedule

    body = await request.json()
    schedule = ReportSchedule(
        tenant=tenant_id,
        frequency=body.get("frequency", "monthly"),
        recipients=body.get("recipients", []),
        format=body.get("format", "pdf"),
        created_at=time.time(),
    )
    await save_schedule(schedule)
    return {"tenant": tenant_id, "schedule": schedule.model_dump(), "status": "scheduled"}


@router.get("/v1/reports/{tenant_id}/schedule", tags=["Reports"])
async def get_report_schedule(tenant_id: str):
    """Get the current report schedule for a tenant."""
    from aion.reports.scheduler import get_schedule
    schedule = await get_schedule(tenant_id)
    if schedule is None:
        return {"tenant": tenant_id, "schedule": None}
    return {"tenant": tenant_id, "schedule": schedule.model_dump()}


@router.delete("/v1/reports/{tenant_id}/schedule", tags=["Reports"])
async def delete_report_schedule(tenant_id: str):
    """Remove the report schedule for a tenant."""
    from aion.reports.scheduler import delete_schedule
    await delete_schedule(tenant_id)
    return {"tenant": tenant_id, "status": "deleted"}
