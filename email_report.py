"""Email-client-friendly HTML rendering for CSAT insight reports.

Uses inline styles and table-based charts so the report remains readable in
Gmail/Outlook even when remote images, JavaScript and external CSS are blocked.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any


def _e(value: Any) -> str:
    if value is None:
        return "—"
    return escape(str(value), quote=True)


def _num(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "0"


def _section(title: str, subtitle: str = "") -> str:
    extra = f'<p style="margin:4px 0 0;color:#64748b;font-size:12px;line-height:1.5">{_e(subtitle)}</p>' if subtitle else ""
    return (
        '<tr><td style="padding:22px 26px 8px">'
        f'<h2 style="margin:0;color:#102a43;font-size:18px;line-height:1.35">{_e(title)}</h2>{extra}'
        '</td></tr>'
    )


def _paragraph(text: Any, color: str = "#334155") -> str:
    return f'<p style="margin:0 0 10px;color:{color};font-size:13px;line-height:1.65">{_e(text)}</p>'


def _list(items: Any, empty: str = "No items were recorded.") -> str:
    if not isinstance(items, list) or not items:
        return _paragraph(empty, "#64748b")
    bits = []
    for item in items:
        if isinstance(item, dict):
            item_text = " · ".join(f"{k}: {v}" for k, v in item.items())
        else:
            item_text = str(item)
        bits.append(
            '<tr><td width="16" valign="top" style="padding:5px 0;color:#2563eb;font-size:15px">•</td>'
            f'<td style="padding:5px 0;color:#334155;font-size:13px;line-height:1.55">{_e(item_text)}</td></tr>'
        )
    return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">' + "".join(bits) + '</table>'


def _html_table(headers: list[str], rows: list[list[Any]], empty: str = "No records for this period.", compact: bool = False) -> str:
    if not rows:
        return f'<p style="margin:8px 0;color:#64748b;font-size:12px">{_e(empty)}</p>'
    pad = "6px 7px" if compact else "9px 10px"
    font = "11px" if compact else "12px"
    out = [
        '<table role="table" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;border-collapse:collapse;margin:8px 0 4px;font-family:Arial,Helvetica,sans-serif">',
        '<thead><tr>'
    ]
    for header in headers:
        out.append(f'<th align="left" style="padding:{pad};background:#eaf0f8;color:#334155;border-bottom:1px solid #d6e0ed;font-size:{font};font-weight:700">{_e(header)}</th>')
    out.append('</tr></thead><tbody>')
    for idx, row in enumerate(rows):
        bg = "#ffffff" if idx % 2 == 0 else "#f8fafc"
        out.append(f'<tr style="background:{bg}">')
        for cell in row:
            out.append(f'<td valign="top" style="padding:{pad};background:{bg};color:#334155;border-bottom:1px solid #e7edf4;font-size:{font};line-height:1.45;overflow-wrap:anywhere">{_e(cell)}</td>')
        out.append('</tr>')
    out.append('</tbody></table>')
    return "".join(out)


def _bar_chart(title: str, rows: list[dict], label_key: str, value_key: str,
               max_value: float, color_fn, value_label_fn=None, note: str = "") -> str:
    if not rows:
        return _section(title) + f'<tr><td style="padding:0 26px 12px">{_paragraph("No chart data is available for this period.", "#64748b")}</td></tr>'
    chart_rows = []
    for row in rows:
        try:
            val = float(row.get(value_key, 0) or 0)
        except (TypeError, ValueError):
            val = 0.0
        pct = max(0, min(100, round(val / max_value * 100))) if max_value > 0 else 0
        if val > 0:
            pct = max(2, pct)
        color = color_fn(row, val)
        label = _e(row.get(label_key, "—"))
        value_label = value_label_fn(row, val) if value_label_fn else _num(val, 1)
        chart_rows.append(
            '<tr>'
            f'<td width="125" valign="middle" style="padding:7px 8px 7px 0;color:#334155;font-size:12px;line-height:1.35">{label}</td>'
            '<td valign="middle" style="padding:7px 8px 7px 0">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;background:#edf2f7;border-radius:4px"><tr>'
            f'<td width="{pct}%" height="15" bgcolor="{color}" style="height:15px;background:{color};font-size:1px;line-height:1px">&nbsp;</td>'
            f'<td width="{100-pct}%" height="15" style="height:15px;font-size:1px;line-height:1px">&nbsp;</td>'
            '</tr></table></td>'
            f'<td width="95" align="right" valign="middle" style="padding:7px 0;color:#102a43;font-size:12px;font-weight:700">{_e(value_label)}</td>'
            '</tr>'
        )
    subtitle = _paragraph(note, "#64748b") if note else ""
    return (
        _section(title) + '<tr><td style="padding:0 26px 10px">' + subtitle +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse">' +
        "".join(chart_rows) + '</table></td></tr>'
    )


def _alert_color(severity: str) -> tuple[str, str]:
    return {
        "CRITICAL": ("#991b1b", "#fef2f2"),
        "HIGH": ("#9a3412", "#fff7ed"),
        "MEDIUM": ("#854d0e", "#fefce8"),
        "INFO": ("#1d4ed8", "#eff6ff"),
    }.get(str(severity).upper(), ("#475569", "#f8fafc"))


def render_html_report(payload: dict[str, Any]) -> str:
    """Render a complete styled HTML email from analyze_day()'s payload."""
    payload = payload or {}
    metrics = payload.get("metrics") or {}
    insights = payload.get("cx_insights") or {}
    im = insights.get("metrics") or {}
    ai = payload.get("ai_analysis") or {}
    period = payload.get("report_period") or payload.get("report_date") or "Selected period"
    generated = datetime.now().astimezone().strftime("%d %b %Y, %H:%M %Z")

    survey_count = im.get("survey_count", metrics.get("survey_count", 0))
    avg_csat = im.get("average_csat", metrics.get("average_csat", 0))
    positive_pct = im.get("positive_rate_pct", metrics.get("positive_rate_pct", 0))
    low_count = im.get("low_score_count", 0)
    low_pct = im.get("low_rate_pct", metrics.get("low_rate_pct", 0))
    critical_count = im.get("critical_score1_count", 0)
    impacted = im.get("customers_with_low_scores", 0)
    neutral_count = im.get("neutral_count", 0)

    kpis = [
        ("SURVEYS", f"{int(survey_count or 0):,}", "#eaf2ff", "#1d4ed8"),
        ("AVERAGE CSAT", f"{_num(avg_csat, 2)} / 5", "#ecfdf5", "#047857"),
        ("POSITIVE (4–5)", f"{_num(positive_pct, 1)}%", "#ecfdf5", "#047857"),
        ("LOW CSAT (1–2)", f"{int(low_count or 0):,} · {_num(low_pct, 1)}%", "#fff7ed", "#c2410c"),
        ("SCORE-1 CASES", f"{int(critical_count or 0):,}", "#fef2f2", "#b91c1c"),
        ("NAMED CUSTOMERS IMPACTED", f"{int(impacted or 0):,}", "#f5f3ff", "#6d28d9"),
    ]
    kpi_rows = []
    for offset in (0, 3):
        cells = []
        for label, value, bg, fg in kpis[offset:offset+3]:
            cells.append(
                f'<td width="33.33%" valign="top" style="padding:5px">'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;background:{bg};border:1px solid #e2e8f0;border-radius:8px"><tr><td style="padding:12px 10px">'
                f'<div style="font-size:9px;letter-spacing:.6px;color:#64748b;font-weight:700;line-height:1.4">{_e(label)}</div>'
                f'<div style="padding-top:5px;color:{fg};font-size:20px;font-weight:700;line-height:1.25">{_e(value)}</div>'
                '</td></tr></table></td>'
            )
        kpi_rows.append('<tr>' + "".join(cells) + '</tr>')

    alerts = insights.get("alerts") or []
    if alerts:
        alert_parts = []
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}
        for alert in sorted(alerts, key=lambda x: severity_order.get(str(x.get("severity", "INFO")).upper(), 9)):
            sev = str(alert.get("severity", "INFO")).upper()
            fg, bg = _alert_color(sev)
            alert_parts.append(
                f'<tr><td style="padding:7px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;background:{bg};border-left:4px solid {fg}"><tr><td style="padding:11px 13px">'
                f'<div style="color:{fg};font-size:11px;font-weight:700;letter-spacing:.4px">{_e(sev)} ALERT</div>'
                f'<div style="margin-top:4px;color:#102a43;font-size:14px;font-weight:700">{_e(alert.get("title", "Alert"))}</div>'
                f'<div style="margin-top:5px;color:#334155;font-size:12px;line-height:1.55"><b>Signal:</b> {_e(alert.get("metric", ""))}<br>{_e(alert.get("detail", ""))}<br><b>Recommended action:</b> {_e(alert.get("recommendation", ""))}</div>'
                '</td></tr></table></td></tr>'
            )
        alerts_html = '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">' + "".join(alert_parts) + '</table>'
    else:
        alerts_html = '<p style="margin:0;color:#047857;font-size:13px">No rule-based CSAT alerts were triggered for this period.</p>'

    score_rows = insights.get("score_distribution") or []
    score_colors = {1: "#b91c1c", 2: "#ea580c", 3: "#ca8a04", 4: "#65a30d", 5: "#047857"}
    score_chart_rows = sorted(score_rows, key=lambda row: int(row.get("CSAT score", 0)))
    category_rows = (insights.get("category_summary") or [])[:10]
    staff_rows = (insights.get("staff_summary") or [])[:10]
    daily_rows = (insights.get("daily_trend") or [])[-14:]

    score_chart = _bar_chart(
        "CSAT score distribution", score_chart_rows, "CSAT score", "Surveys",
        max([float(r.get("Surveys", 0) or 0) for r in score_chart_rows] + [1]),
        lambda row, val: score_colors.get(int(row.get("CSAT score", 0) or 0), "#64748b"),
        lambda row, val: f"{int(val)} survey(s)", "Bar lengths show survey count per score (1 = lowest, 5 = highest)."
    )
    category_chart = _bar_chart(
        "Categories contributing to low CSAT", category_rows, "Category", "Low CSAT (1-2)",
        max([float(r.get("Low CSAT (1-2)", 0) or 0) for r in category_rows] + [1]),
        lambda row, val: "#dc2626" if val >= 3 else ("#f97316" if val > 0 else "#cbd5e1"),
        lambda row, val: f"{int(val)} low · {_num(row.get('Average CSAT', 0), 2)}/5 avg",
        "Shows low-score records per category; this is an issue-volume signal, not proof of root cause."
    )
    staff_chart_rows = sorted(staff_rows, key=lambda row: float(row.get("Average CSAT", 0) or 0))
    staff_chart = _bar_chart(
        "Staff CSAT comparison", staff_chart_rows, "Staff name", "Average CSAT", 5.0,
        lambda row, val: "#b91c1c" if val < 2.5 else ("#d97706" if val < 3.5 else "#059669"),
        lambda row, val: f"{_num(val, 2)}/5 · {int(row.get('Surveys', 0) or 0)} survey(s)",
        "Averages are shown with survey volume. Small samples can be unstable and do not prove individual staff causality."
    )
    daily_chart = _bar_chart(
        "Daily CSAT trend (latest 14 dates)", daily_rows, "Date", "Average CSAT", 5.0,
        lambda row, val: "#b91c1c" if val < 2.5 else ("#d97706" if val < 3.5 else "#059669"),
        lambda row, val: f"{_num(val, 2)}/5 · {int(row.get('Surveys', 0) or 0)} survey(s)",
        "Each bar is the daily average CSAT on a 0–5 scale."
    )

    category_table_rows = [[
        row.get("Category", ""), row.get("Surveys", 0), f"{_num(row.get('Average CSAT', 0), 2)}/5",
        row.get("Low CSAT (1-2)", 0), f"{_num(row.get('Low CSAT %', 0), 1)}%", row.get("Named customers impacted", 0)
    ] for row in (insights.get("category_summary") or [])[:15]]
    staff_table_rows = [[
        row.get("Staff ID", ""), row.get("Staff name", ""), row.get("Surveys", 0),
        f"{_num(row.get('Average CSAT', 0), 2)}/5", row.get("Low CSAT (1-2)", 0), f"{_num(row.get('Low CSAT %', 0), 1)}%"
    ] for row in (insights.get("staff_summary") or [])[:15]]
    theme_table_rows = [[row.get("Theme signal", ""), row.get("Keyword matches", 0)] for row in (insights.get("keyword_themes") or [])[:10]]
    recovery_rows = []
    for row in (insights.get("recovery_queue") or [])[:10]:
        comment = str(row.get("CustomerComment", "") or "")
        if len(comment) > 180:
            comment = comment[:177] + "..."
        flight = str(row.get("FlightNumber", "") or "").strip()
        airport = str(row.get("Airport", "") or "").strip()
        flight_airport = " / ".join(part for part in (flight, airport) if part) or "—"
        recovery_rows.append([
            row.get("Priority", ""), row.get("SurveyDate", ""), row.get("CustomerName", ""),
            row.get("CSATScore", ""), row.get("Category", ""), row.get("StaffName", ""),
            flight_airport, comment or "No comment provided"
        ])

    insights_section = _section("Executive summary & customer impact") + '<tr><td style="padding:0 26px 8px">' + _paragraph(insights.get("executive_summary", "No executive summary available.")) + '</td></tr>'
    insight_bullets = insights.get("insight_bullets") or []
    if insight_bullets:
        insights_section += '<tr><td style="padding:0 26px 12px">' + _list(insight_bullets) + '</td></tr>'

    actions = insights.get("recommendations") or (ai.get("recommended_actions") or [])
    alert_section = _section("Alerts & priorities") + '<tr><td style="padding:0 26px 12px">' + alerts_html + '</td></tr>'
    recommendations_section = _section("Recommended next actions") + '<tr><td style="padding:0 26px 14px">' + _list(actions, "No additional actions generated.") + '</td></tr>'

    ai_sections = []
    if ai.get("sentiment_summary"):
        ai_sections.append(('<b>Sentiment summary</b>', ai.get("sentiment_summary")))
    for title, key in [
        ("Recurring issue signals", "recurring_issues"),
        ("Positive themes", "positive_themes"),
        ("Root-cause hypotheses to validate", "root_cause_hypotheses"),
    ]:
        value = ai.get(key)
        if value:
            ai_sections.append((title, value))
    if ai_sections:
        ai_bits = []
        for title, value in ai_sections:
            if isinstance(value, list):
                value_html = _list(value)
            elif isinstance(value, dict):
                value_html = _list([f"{k}: {v}" for k, v in value.items()])
            else:
                value_html = _paragraph(value)
            ai_bits.append(f'<tr><td style="padding:7px 0"><div style="font-size:13px;font-weight:700;color:#334155;margin-bottom:5px">{_e(title)}</div>{value_html}</td></tr>')
        ai_section = _section("Feedback interpretation") + '<tr><td style="padding:0 26px 12px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">' + "".join(ai_bits) + '</table><p style="margin:8px 0;color:#64748b;font-size:11px">Interpretive themes and possible root causes are not confirmed facts. Validate against comments and operational records.</p></td></tr>'
    else:
        ai_section = ""

    recovery_section = _section("Customer recovery queue", "Highest-priority low-score records; comments are shortened for email readability.") + '<tr><td style="padding:0 26px 16px">' + _html_table(
        ["Priority", "Date", "Customer", "Score", "Category", "Staff", "Flight / airport", "Feedback"], recovery_rows,
        "There are no low-score records in this period.", compact=True
    ) + '</td></tr>'
    category_section = _section("Category performance table") + '<tr><td style="padding:0 26px 16px">' + _html_table(
        ["Category", "Surveys", "Avg CSAT", "Low scores", "Low %", "Named customers"], category_table_rows, compact=True
    ) + '</td></tr>'
    staff_section = _section("Staff performance table") + '<tr><td style="padding:0 26px 16px">' + _html_table(
        ["Staff ID", "Staff name", "Surveys", "Avg CSAT", "Low scores", "Low %"], staff_table_rows, compact=True
    ) + '<p style="font-size:10px;line-height:1.5;color:#64748b">Staff comparisons are descriptive and should not be used alone as an employee-performance judgment.</p></td></tr>'
    themes_section = _section("Feedback text signals") + '<tr><td style="padding:0 26px 16px">' + _html_table(["Theme signal", "Keyword matches"], theme_table_rows, compact=True) + '<p style="font-size:11px;line-height:1.5;color:#64748b">Keyword matches indicate patterns in comments; they do not prove the cause of a low score.</p></td></tr>'

    quality_notes = insights.get("data_quality_notes") or payload.get("data_quality_notes") or []
    footer_notes = "".join(f'<li style="margin:0 0 5px">{_e(note)}</li>' for note in quality_notes)
    footer = (
        '<tr><td style="padding:18px 26px;background:#f1f5f9;border-top:1px solid #dbe4ef">'
        '<p style="margin:0 0 7px;font-size:11px;color:#475569;line-height:1.5">Generated by the CSAT Feedback Agent · This email contains summary analytics and customer feedback for the selected report period.</p>'
        f'<p style="margin:0 0 8px;font-size:10px;color:#64748b">Generated { _e(generated) }</p>'
        f'<ul style="margin:0;padding-left:18px;font-size:10px;color:#64748b;line-height:1.5">{footer_notes}</ul>'
        '</td></tr>'
    )

    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Customer Feedback Report</title></head>'
        '<body style="margin:0;padding:0;background:#eef2f7;font-family:Arial,Helvetica,sans-serif;color:#334155">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;background:#eef2f7"><tr><td align="center" style="padding:22px 8px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:760px;background:#ffffff;border:1px solid #dce4ee;border-radius:10px;overflow:hidden">'
        '<tr><td style="padding:25px 26px;background:#102a43;background-color:#102a43">'
        '<div style="color:#9ec5fe;font-size:10px;text-transform:uppercase;letter-spacing:1.8px;font-weight:700">Customer Experience Intelligence</div>'
        '<h1 style="margin:8px 0 5px;color:#ffffff;font-size:25px;line-height:1.25">Customer Feedback Report</h1>'
        f'<p style="margin:0;color:#d9e6f2;font-size:14px;line-height:1.5">Reporting period: <b>{_e(period)}</b></p>'
        '</td></tr>'
        '<tr><td style="padding:15px 21px 8px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">' + "".join(kpi_rows) + '</table></td></tr>'
        + insights_section + alert_section
        + _section("Visual performance charts", "Email-safe charts are built with inline tables and colored bars; no external image download is required.")
        + score_chart + category_chart + staff_chart + daily_chart
        + category_section + staff_section + recovery_section + themes_section + ai_section + recommendations_section + footer
        + '</table></td></tr></table></body></html>'
    )
    return html
