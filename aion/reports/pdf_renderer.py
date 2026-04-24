"""PDF renderer — generates 4-page executive report via reportlab."""

from __future__ import annotations

import io
import logging
from typing import Any

logger = logging.getLogger("aion.reports.pdf_renderer")


def render_pdf(data: dict[str, Any]) -> bytes:
    """Render executive report PDF. Returns PDF bytes.

    Falls back to a plain-text stub if reportlab is unavailable.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        return _render_with_reportlab(data, A4, getSampleStyleSheet, ParagraphStyle, cm, colors,
                                      SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable)
    except ImportError:
        logger.warning("reportlab not installed — returning plain-text report stub")
        return _render_text_fallback(data)
    except Exception as exc:
        logger.error("PDF render failed: %s", exc, exc_info=True)
        return _render_text_fallback(data)


def _render_with_reportlab(data, A4, getSampleStyleSheet, ParagraphStyle, cm, colors,
                           SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=2.5*cm, bottomMargin=2*cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=20, spaceAfter=6)
    h1_style = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=14, spaceAfter=4)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=11, spaceAfter=3)
    body_style = styles["BodyText"]

    tenant = data.get("tenant", "")
    period = data.get("period_days", 30)
    generated_at = data.get("generated_at", "")
    econ = data.get("economics", {})
    sec = data.get("security", {})
    sess = data.get("sessions", {})
    intel = data.get("intelligence", {})
    budget = data.get("budget", {})

    story = []

    # ── Page 1: Cover ──────────────────────────────────────────────────────
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("AION Executive Report", title_style))
    story.append(Paragraph(f"Tenant: <b>{tenant}</b>", body_style))
    story.append(Paragraph(f"Period: last {period} days", body_style))
    story.append(Paragraph(f"Generated: {generated_at}", body_style))
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
    story.append(Spacer(1, 0.3*cm))

    saved = econ.get("total_saved_usd", 0)
    blocked = sec.get("requests_blocked", 0)
    pii = sec.get("pii_intercepted", 0)
    story.append(Paragraph("Executive Summary", h1_style))
    story.append(Paragraph(f"• <b>${saved:.2f}</b> saved in LLM costs through intelligent routing", body_style))
    story.append(Paragraph(f"• <b>{blocked}</b> security threats blocked before reaching the LLM", body_style))
    story.append(Paragraph(f"• <b>{pii}</b> PII incidents intercepted (LGPD/GDPR compliance)", body_style))
    story.append(Spacer(1, 1*cm))

    # ── Page 2: Security ───────────────────────────────────────────────────
    story.append(Paragraph("Security", h1_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2*cm))
    sec_data = [
        ["Metric", "Value"],
        ["Requests blocked", str(blocked)],
        ["PII incidents intercepted", str(pii)],
        ["Sessions audited", str(sess.get("total", 0))],
        ["Verified sessions (HMAC)", str(sess.get("verified", 0))],
        ["Audit verification rate", f"{sess.get('verification_rate', 0)*100:.0f}%"],
    ]
    t = Table(sec_data, colWidths=[10*cm, 5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d3748")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))

    # ── Page 3: Economics ─────────────────────────────────────────────────
    story.append(Paragraph("Economics", h1_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2*cm))
    econ_data = [
        ["Metric", "Value"],
        ["Total LLM cost", f"${econ.get('total_cost_usd', 0):.4f}"],
        ["Total saved", f"${econ.get('total_saved_usd', 0):.4f}"],
        ["Tokens saved (METIS)", str(intel.get("tokens_saved", 0))],
        ["Compression ratio", f"{intel.get('compression_ratio', 0)*100:.1f}%"],
        ["Days with activity", str(econ.get("days_with_data", 0))],
    ]
    if budget.get("config"):
        cfg = budget["config"]
        if cfg.get("daily_cap"):
            econ_data.append(["Daily cap", f"${cfg['daily_cap']:.2f}"])
        econ_data.append(["Today's spend", f"${budget.get('today_spend_usd', 0):.4f}"])

    t2 = Table(econ_data, colWidths=[10*cm, 5*cm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d3748")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t2)
    story.append(Spacer(1, 0.5*cm))

    # Model distribution
    dist = econ.get("model_distribution", {})
    if dist:
        story.append(Paragraph("Model Distribution", h2_style))
        total_reqs = sum(dist.values()) or 1
        rows = [["Model", "Requests", "Share"]]
        for model, count in sorted(dist.items(), key=lambda x: -x[1]):
            rows.append([model, str(count), f"{count/total_reqs*100:.0f}%"])
        t3 = Table(rows, colWidths=[8*cm, 4*cm, 3*cm])
        t3.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4a5568")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t3)
        story.append(Spacer(1, 0.3*cm))

    # ── Page 4: Intelligence / Learning ───────────────────────────────────
    story.append(Paragraph("Intelligence & Learning", h1_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2*cm))

    top_intents = intel.get("top_intents", [])
    if top_intents:
        story.append(Paragraph("Top Intent Patterns", h2_style))
        rows = [["Intent", "Bypass Rate", "Samples"]]
        for item in top_intents[:10]:
            rows.append([
                item.get("intent", ""),
                f"{item.get('bypass_success_rate', 0)*100:.0f}%",
                str(item.get("sample_count", 0)),
            ])
        t4 = Table(rows, colWidths=[9*cm, 4*cm, 2*cm])
        t4.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4a5568")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t4)
        story.append(Spacer(1, 0.3*cm))

    model_perf = intel.get("model_performance", [])
    if model_perf:
        story.append(Paragraph("Model Performance", h2_style))
        rows = [["Model", "Success Rate", "Avg Latency", "Avg Cost"]]
        for item in model_perf[:8]:
            rows.append([
                item.get("model", ""),
                f"{item.get('success_rate', 0)*100:.0f}%",
                f"{item.get('avg_latency_ms', 0):.0f}ms",
                f"${item.get('avg_cost', 0):.5f}",
            ])
        t5 = Table(rows, colWidths=[7*cm, 3*cm, 3*cm, 2*cm])
        t5.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4a5568")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t5)

    doc.build(story)
    return buf.getvalue()


def _render_text_fallback(data: dict[str, Any]) -> bytes:
    import json
    text = f"AION Executive Report\nTenant: {data.get('tenant')}\n\n{json.dumps(data, indent=2)}"
    return text.encode("utf-8")
