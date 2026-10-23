"""Evidence-based CSAT insights, alerts and customer-recovery metrics.

All counts and percentages are calculated from the supplied dataframe. Text
signals are transparent keyword heuristics, not claims of confirmed root cause.
"""
from __future__ import annotations

import math
import re
from typing import Any
import pandas as pd

_UNKNOWN_NAMES = {"", "unknown", "unknown customer", "n/a", "na", "anonymous", "none", "null"}

_THEME_RULES = {
    "Delays / waiting": ("delay", "delayed", "late", "wait", "waiting", "queue", "long line"),
    "Baggage": ("baggage", "luggage", "suitcase", "lost bag", "damaged bag", "missing bag"),
    "Booking / ticket changes": ("booking", "ticket", "rebook", "reschedule", "change flight", "cancel", "cancellation"),
    "Refund / payment": ("refund", "money back", "charged", "payment", "fee", "invoice"),
    "Communication / information": ("no information", "not informed", "communication", "update", "unclear", "explain"),
    "Staff interaction": ("rude", "unhelpful", "staff", "agent", "representative", "attitude", "polite"),
    "Check-in / boarding": ("check-in", "check in", "boarding", "gate", "boarding pass", "kiosk"),
    "Digital / technical issue": ("app", "website", "system", "error", "online", "technical", "crash"),
    "Accessibility / assistance": ("wheelchair", "accessibility", "special assistance", "mobility", "assistance"),
}


def _clean_name(value: Any) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _is_known_name(value: Any) -> bool:
    name = _clean_name(value)
    return bool(name) and name.casefold() not in _UNKNOWN_NAMES


def _distinct_customer_count(frame: pd.DataFrame) -> int:
    if frame.empty or "CustomerName" not in frame.columns:
        return 0
    names = frame["CustomerName"].map(_clean_name)
    names = names[names.map(_is_known_name)].str.casefold()
    return int(names.nunique())


def prepare_insight_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize columns/types needed by insight calculations without mutating input."""
    frame = df.copy() if df is not None else pd.DataFrame()
    if frame.empty:
        return frame
    if "SurveyDate" in frame.columns:
        frame["SurveyDate"] = pd.to_datetime(frame["SurveyDate"], errors="coerce", format="mixed").dt.date
    else:
        frame["SurveyDate"] = pd.NaT
    if "CSATScore" not in frame.columns:
        frame["CSATScore"] = pd.NA
    frame["CSATScore"] = pd.to_numeric(frame["CSATScore"], errors="coerce")
    frame = frame.dropna(subset=["CSATScore"]).copy()
    for column, default in {
        "SurveyID": "", "CustomerName": "Unknown Customer", "CustomerComment": "",
        "Category": "Uncategorized", "StaffID": "", "StaffName": "Unknown",
        "FlightNumber": "", "Airport": "",
    }.items():
        if column not in frame.columns:
            frame[column] = default
        frame[column] = frame[column].fillna(default).astype(str).str.strip()
        frame.loc[frame[column].eq(""), column] = default
    frame["Category"] = frame["Category"].replace({"": "Uncategorized"})
    return frame


def _records(frame: pd.DataFrame, columns: list[str], limit: int | None = None) -> list[dict]:
    existing = [column for column in columns if column in frame.columns]
    view = frame[existing].copy()
    if limit is not None:
        view = view.head(limit)
    out = []
    for row in view.to_dict("records"):
        clean = {}
        for key, value in row.items():
            if pd.isna(value):
                clean[key] = ""
            elif hasattr(value, "isoformat"):
                clean[key] = value.isoformat()
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                clean[key] = round(float(value), 2) if isinstance(value, float) else int(value)
            else:
                clean[key] = str(value)
        out.append(clean)
    return out


def build_csat_insights(df: pd.DataFrame) -> dict:
    """Return metrics, prioritised alerts, charts' data and recovery cases."""
    frame = prepare_insight_frame(df)
    if frame.empty:
        return {
            "metrics": {"survey_count": 0, "average_csat": 0.0, "positive_count": 0,
                        "positive_rate_pct": 0.0, "low_score_count": 0, "low_rate_pct": 0.0,
                        "critical_score1_count": 0, "customers_with_low_scores": 0,
                        "named_customer_count": 0, "neutral_count": 0},
            "executive_summary": "No valid CSAT scores are available for the selected period.",
            "alerts": [], "insight_bullets": ["Load valid feedback rows to generate insights."],
            "recommendations": ["Verify the data source and selected date range."],
            "score_distribution": [], "daily_trend": [], "category_summary": [],
            "staff_summary": [], "recovery_queue": [], "keyword_themes": [],
            "data_quality_notes": ["Customer impact counts use distinct non-empty CustomerName values; names are not a verified customer identifier."],
        }

    count = int(len(frame))
    score = frame["CSATScore"]
    low = frame[score.le(2)].copy()
    critical = frame[score.eq(1)].copy()
    positive = frame[score.ge(4)]
    known_names = frame[frame["CustomerName"].map(_is_known_name)]
    impacted_named_customers = _distinct_customer_count(low)
    low_rate = (len(low) / count * 100) if count else 0.0
    average = float(score.mean()) if count else 0.0
    metrics = {
        "survey_count": count,
        "average_csat": round(average, 2),
        "positive_count": int(len(positive)),
        "positive_rate_pct": round(len(positive) / count * 100, 1) if count else 0.0,
        "low_score_count": int(len(low)),
        "low_rate_pct": round(low_rate, 1),
        "critical_score1_count": int(len(critical)),
        "customers_with_low_scores": impacted_named_customers,
        "named_customer_count": _distinct_customer_count(known_names),
        "neutral_count": int(score.eq(3).sum()),
    }

    score_counts = score.value_counts().reindex([1, 2, 3, 4, 5], fill_value=0)
    score_distribution = [{"CSAT score": int(k), "Surveys": int(v)} for k, v in score_counts.items()]

    # Category-level impact: low-score records and distinct names represented.
    category_rows = []
    for category, group in frame.groupby("Category", dropna=False):
        low_group = group[group["CSATScore"].le(2)]
        category_rows.append({
            "Category": str(category),
            "Surveys": int(len(group)),
            "Average CSAT": round(float(group["CSATScore"].mean()), 2),
            "Low CSAT (1-2)": int(len(low_group)),
            "Low CSAT %": round(len(low_group) / len(group) * 100, 1) if len(group) else 0.0,
            "Named customers impacted": _distinct_customer_count(low_group),
        })
    category_summary = sorted(category_rows, key=lambda item: (item["Low CSAT (1-2)"], -item["Surveys"]), reverse=True)

    # Staff breakdown includes volume alongside averages to avoid overinterpreting small samples.
    staff_rows = []
    for (staff_id, staff_name), group in frame.groupby(["StaffID", "StaffName"], dropna=False):
        staff_low = group[group["CSATScore"].le(2)]
        staff_rows.append({
            "Staff ID": str(staff_id), "Staff name": str(staff_name), "Surveys": int(len(group)),
            "Average CSAT": round(float(group["CSATScore"].mean()), 2),
            "Low CSAT (1-2)": int(len(staff_low)),
            "Low CSAT %": round(len(staff_low) / len(group) * 100, 1) if len(group) else 0.0,
        })
    staff_summary = sorted(staff_rows, key=lambda item: (item["Average CSAT"], -item["Surveys"]))

    daily = frame[frame["SurveyDate"].notna()].groupby("SurveyDate").agg(
        surveys=("CSATScore", "count"), average_csat=("CSATScore", "mean"),
        low_surveys=("CSATScore", lambda values: int((values <= 2).sum())),
    ).reset_index().sort_values("SurveyDate")
    daily_trend = [{"Date": str(row.SurveyDate), "Surveys": int(row.surveys),
                    "Average CSAT": round(float(row.average_csat), 2),
                    "Low CSAT (1-2)": int(row.low_surveys)} for row in daily.itertuples(index=False)]

    # Customer recovery queue prioritises score-1 first, then score-2, most recent first.
    recovery = low.copy()
    recovery["Priority"] = recovery["CSATScore"].map(lambda value: "CRITICAL" if value <= 1 else "HIGH")
    if "SurveyDate" in recovery:
        recovery = recovery.sort_values(["CSATScore", "SurveyDate"], ascending=[True, False])
    queue_cols = ["Priority", "SurveyDate", "SurveyID", "CustomerName", "CSATScore", "Category",
                  "StaffName", "FlightNumber", "Airport", "CustomerComment"]
    recovery_queue = _records(recovery, queue_cols, limit=100)

    alerts = []
    if len(critical):
        alerts.append({
            "severity": "CRITICAL", "title": "Urgent customer recovery needed",
            "metric": f"{len(critical)} score-1 survey(s)",
            "detail": f"{_distinct_customer_count(critical)} distinct named customer(s) appear in the score-1 records.",
            "recommendation": "Prioritise these cases for prompt human review and recovery; confirm the customer's desired outcome.",
            "records": int(len(critical)),
        })
    if len(low):
        severity = "HIGH" if low_rate >= 20 or len(low) >= 3 else ("MEDIUM" if low_rate >= 10 else "INFO")
        alerts.append({
            "severity": severity, "title": "Low-CSAT feedback needs review",
            "metric": f"{len(low)} of {count} surveys ({low_rate:.1f}%) scored 1-2",
            "detail": f"{impacted_named_customers} distinct named customer(s) are represented in low-score records.",
            "recommendation": "Review the recovery queue and group cases by issue category before assigning follow-up.",
            "records": int(len(low)),
        })
    if category_summary and len(low):
        top_low = max(category_summary, key=lambda item: item["Low CSAT (1-2)"])
        share = (top_low["Low CSAT (1-2)"] / len(low) * 100) if len(low) else 0
        if top_low["Low CSAT (1-2)"] >= 2 and share >= 40:
            alerts.append({
                "severity": "HIGH" if top_low["Low CSAT (1-2)"] >= 4 else "MEDIUM",
                "title": f"Repeated issue signal: {top_low['Category']}",
                "metric": f"{top_low['Low CSAT (1-2)']} low-score records ({share:.0f}% of low CSAT)",
                "detail": f"This category is the largest contributor to low scores in the selected period; {top_low['Named customers impacted']} distinct named customers appear in those records.",
                "recommendation": f"Review the comments in {top_low['Category']} and verify the suspected operational cause before changing process.",
                "records": int(top_low["Low CSAT (1-2)"]),
            })

    # Conservative trend alert: only flag a decline when both comparison windows have volume.
    if len(daily) >= 4:
        recent = daily.tail(3)
        previous = daily.iloc[max(0, len(daily) - 6):len(daily) - 3]
        if len(previous) >= 2 and int(recent["surveys"].sum()) >= 3 and int(previous["surveys"].sum()) >= 3:
            recent_avg = float((recent["average_csat"] * recent["surveys"]).sum() / recent["surveys"].sum())
            previous_avg = float((previous["average_csat"] * previous["surveys"]).sum() / previous["surveys"].sum())
            delta = recent_avg - previous_avg
            if delta <= -0.5:
                alerts.append({
                    "severity": "MEDIUM", "title": "CSAT has recently declined",
                    "metric": f"{previous_avg:.2f}/5 → {recent_avg:.2f}/5 ({delta:+.2f})",
                    "detail": "The volume-weighted average over the latest available days is lower than the prior comparison window.",
                    "recommendation": "Compare issue mix and operational conditions across the two periods; treat this as a signal, not a causal conclusion.",
                    "records": int(recent["surveys"].sum()),
                })

    if len(low) and not low["CustomerComment"].str.strip().astype(bool).any():
        alerts.append({
            "severity": "MEDIUM", "title": "Low-score feedback lacks comments",
            "metric": f"{len(low)} low-score record(s) without useful written detail",
            "detail": "Scores alone do not explain the customer issue.",
            "recommendation": "Use the follow-up workflow to ask for context and record the recovery outcome.",
            "records": int(len(low)),
        })

    theme_counts = []
    low_text = "\n".join(low["CustomerComment"].astype(str).str.casefold().tolist())
    for theme, keywords in _THEME_RULES.items():
        hits = sum(len(re.findall(re.escape(keyword), low_text)) for keyword in keywords)
        if hits:
            theme_counts.append({"Theme signal": theme, "Keyword matches": int(hits)})
    theme_counts.sort(key=lambda row: row["Keyword matches"], reverse=True)

    if len(low):
        top_category_text = f"The most common low-CSAT category is {category_summary[0]['Category']} ({category_summary[0]['Low CSAT (1-2)']} records)." if category_summary else "Review low-score categories."
        summary = (f"Across **{count} surveys**, average CSAT is **{average:.2f}/5**. "
                   f"**{len(low)} ({low_rate:.1f}%)** scored 1–2, including **{len(critical)} score-1 case(s)**. "
                   f"**{impacted_named_customers} distinct named customer(s)** are represented in low-score records. {top_category_text}")
    else:
        summary = (f"Across **{count} surveys**, average CSAT is **{average:.2f}/5** and no score-1/2 responses were recorded. "
                   "Continue monitoring the trend and review comments for early warning signals.")

    recommendations = []
    if len(critical):
        recommendations.append("Prioritise score-1 cases for prompt human follow-up; record ownership and recovery outcome.")
    if len(low) and category_summary:
        top_category = max(category_summary, key=lambda item: item["Low CSAT (1-2)"])
        recommendations.append(f"Investigate {top_category['Category']} first ({top_category['Low CSAT (1-2)']} low-score record(s); {top_category['Named customers impacted']} named customer(s)).")
    if theme_counts:
        recommendations.append(f"Validate the top text signal, {theme_counts[0]['Theme signal']}, by reading the original comments; keyword matching is indicative only.")
    if not recommendations:
        recommendations.append("Maintain service controls and watch for changes in score mix and feedback themes.")

    if len(low):
        insight_bullets = [
            f"Low-CSAT rate: {low_rate:.1f}% ({len(low)}/{count} surveys).",
            f"Score-1 cases: {len(critical)}; distinct named customers in low-score records: {impacted_named_customers}.",
        ]
        if category_summary:
            top_cat = max(category_summary, key=lambda item: item["Low CSAT (1-2)"])
            insight_bullets.append(f"Largest low-score category: {top_cat['Category']} ({top_cat['Low CSAT (1-2)']} records).")
        if theme_counts:
            insight_bullets.append(f"Feedback-text keyword signal: {theme_counts[0]['Theme signal']} ({theme_counts[0]['Keyword matches']} matches); validate manually.")
    else:
        insight_bullets = ["No low-score surveys in the selected period.", f"Positive CSAT (4-5): {len(positive)}/{count} ({metrics['positive_rate_pct']:.1f}%)."]

    return {
        "metrics": metrics,
        "executive_summary": summary,
        "alerts": alerts,
        "insight_bullets": insight_bullets,
        "recommendations": recommendations,
        "score_distribution": score_distribution,
        "daily_trend": daily_trend,
        "category_summary": category_summary,
        "staff_summary": staff_summary,
        "recovery_queue": recovery_queue,
        "keyword_themes": theme_counts,
        "data_quality_notes": [
            "Customer impact is calculated as distinct non-empty CustomerName values among low-CSAT records; it is not a verified unique-customer ID count.",
            "Category/root-cause theme signals are descriptive patterns. Verify original comments and operational data before concluding cause.",
            "Staff comparisons should include survey volume and are not proof that an individual staff member caused an outcome.",
        ],
    }


def insight_answer(df: pd.DataFrame, question: str) -> str | None:
    """Answer high-value insight/risk/customer-impact questions from computed facts."""
    q = re.sub(r"[^a-z0-9\s-]", " ", str(question or "").casefold())
    q = re.sub(r"\s+", " ", q).strip()
    if not q:
        return None

    insights = build_csat_insights(df)
    metrics = insights["metrics"]
    frame = prepare_insight_frame(df)
    if frame.empty:
        return "I don't have valid scored feedback in this date range. Refresh the live data or choose a different range."

    def table(records: list[dict], columns: list[str], max_rows: int = 12) -> str:
        existing = [c for c in columns if any(c in row for row in records)]
        if not records or not existing:
            return "No matching records found."
        rows = ["| " + " | ".join(existing) + " |", "| " + " | ".join(["---"] * len(existing)) + " |"]
        for row in records[:max_rows]:
            vals = []
            for column in existing:
                value = str(row.get(column, ""))
                value = value.replace("|", "\\|").replace("\n", " ")[:180]
                vals.append(value)
            rows.append("| " + " | ".join(vals) + " |")
        return "\n".join(rows)

    # Match a named category if the question contains one; use it to narrow impact queries.
    categories = sorted(frame["Category"].dropna().astype(str).unique().tolist(), key=len, reverse=True)
    matched_category = next((category for category in categories if category.casefold() in q), None)
    low = frame[frame["CSATScore"].le(2)].copy()
    if matched_category and any(word in q for word in ("customer", "impact", "affected", "impacted", "alert", "complaint", "low score", "priority", "issue")):
        low = low[low["Category"].astype(str).str.casefold() == matched_category.casefold()]
    matched_flight = next((str(v) for v in sorted(frame["FlightNumber"].dropna().astype(str).unique(), key=len, reverse=True) if str(v).casefold() and str(v).casefold() in q), None)
    matched_airport = next((str(v) for v in sorted(frame["Airport"].dropna().astype(str).unique(), key=len, reverse=True) if str(v).casefold() and str(v).casefold() in q), None)
    if matched_flight and any(word in q for word in ("customer", "impact", "affected", "impacted", "alert", "low score", "issue", "complaint", "follow up")):
        low = low[low["FlightNumber"].astype(str).str.casefold() == matched_flight.casefold()]
    if matched_airport and any(word in q for word in ("customer", "impact", "affected", "impacted", "alert", "low score", "issue", "complaint", "follow up")):
        low = low[low["Airport"].astype(str).str.casefold() == matched_airport.casefold()]

    impact_terms = ("customer impact", "impact by category", "impact per category", "customers impacted", "customer impacted", "customers affected", "customer affected",
                    "affected customers", "impacted customers", "who is affected", "which customers", "recovery queue",
                    "follow up customer", "follow-up customer", "need follow up", "recovery cases", "customers need")
    alert_terms = ("alert", "alerts", "risk", "risky", "urgent", "priority", "attention", "red flag", "what need attention",
                   "what should i worry", "what do i need to know", "what needs action", "warning", "critical cases")
    summary_terms = ("executive summary", "overall insight", "insights", "what should we do", "recommend", "recommendation",
                     "action plan", "root cause", "main problem", "main issue", "what is happening", "summarize", "summary", "why are customers")

    if any(term in q for term in impact_terms):
        if any(term in q for term in ("impact by category", "impact per category", "by category", "per category", "grouped by category")):
            category_records = insights["category_summary"]
            return ("**Low-CSAT customer impact by category**\n\n" +
                    table(category_records, ["Category", "Surveys", "Average CSAT", "Low CSAT (1-2)", "Low CSAT %", "Named customers impacted"], 25) +
                    "\n\nNamed customer counts are based on distinct CustomerName values within low-score records, not a verified customer ID.")
        if low.empty:
            return "**Customer recovery:** no low-CSAT records (score 1–2) matched this question in the selected date range.\n\n" + insights["executive_summary"]
        customer_count = _distinct_customer_count(low)
        scope_notes = []
        if matched_category:
            scope_notes.append(f"**category {matched_category}**")
        if matched_flight:
            scope_notes.append(f"flight {matched_flight}")
        if matched_airport:
            scope_notes.append(f"airport {matched_airport}")
        scoped_to = f" for {', '.join(scope_notes)}" if scope_notes else ""
        named_names = low[low["CustomerName"].map(_is_known_name)].copy()
        grouped_records = []
        if not named_names.empty:
            grouped = named_names.groupby(named_names["CustomerName"].str.casefold()).agg(
                customer_name=("CustomerName", "first"), low_score_surveys=("CSATScore", "count"),
                lowest_score=("CSATScore", "min"), latest_date=("SurveyDate", "max"),
                categories=("Category", lambda x: ", ".join(sorted(set(map(str, x))))),
            ).reset_index(drop=True).sort_values(["lowest_score", "low_score_surveys"], ascending=[True, False])
            for row in grouped.to_dict("records"):
                grouped_records.append({
                    "Customer": row["customer_name"], "Low-score surveys": int(row["low_score_surveys"]),
                    "Lowest score": int(row["lowest_score"]), "Latest date": str(row["latest_date"]),
                    "Categories": row["categories"],
                })
        answer = (f"**Customer impact{scoped_to}:** {len(low)} low-CSAT survey record(s) represent "
                  f"**{customer_count} distinct named customer(s)**. This counts distinct names, not verified customer IDs.\n\n")
        answer += table(grouped_records, ["Customer", "Low-score surveys", "Lowest score", "Latest date", "Categories"])
        answer += "\n\nCases are ordered by lowest score first. Use this as a follow-up queue; it does not prove each case has been recovered."
        if any(term in q for term in alert_terms):
            answer += "\n\n## Related alerts"
            if insights["alerts"]:
                for alert in insights["alerts"]:
                    answer += f"\n- **[{alert['severity']}] {alert['title']}** — {alert['metric']}. Action: {alert['recommendation']}"
            else:
                answer += "\nNo rule-based alerts were triggered in this period."
        return answer

    if any(term in q for term in alert_terms):
        if not insights["alerts"]:
            return "**Current alert status: no rule-based CSAT alerts were triggered** for this date range. Continue watching the trend and comments.\n\n" + insights["executive_summary"]
        lines = ["## Current CSAT alerts", ""]
        for alert in insights["alerts"]:
            lines.extend([
                f"### [{alert['severity']}] {alert['title']}",
                f"**Signal:** {alert['metric']}", alert["detail"],
                f"**Recommended action:** {alert['recommendation']}", "",
            ])
        lines.extend(["## Executive readout", insights["executive_summary"]])
        return "\n".join(lines)

    if any(term in q for term in summary_terms):
        lines = ["## Executive summary", insights["executive_summary"], "", "## Key insights"]
        lines.extend([f"- {item}" for item in insights["insight_bullets"]])
        lines.extend(["", "## Recommended next actions"])
        lines.extend([f"- {item}" for item in insights["recommendations"]])
        if insights["keyword_themes"]:
            lines.extend(["", "## Feedback text signals", table(insights["keyword_themes"], ["Theme signal", "Keyword matches"])])
            lines.append("These are keyword-based signals, not a confirmed root-cause analysis.")
        return "\n".join(lines)

    if matched_category and any(term in q for term in ("why", "cause", "root", "low csat", "low score", "problem", "issue", "complaint", "explain", "improve")):
        subset = frame[frame["Category"].astype(str).str.casefold() == matched_category.casefold()].copy()
        subset_low = subset[subset["CSATScore"].le(2)]
        avg = float(subset["CSATScore"].mean()) if not subset.empty else 0.0
        low_pct = len(subset_low) / len(subset) * 100 if len(subset) else 0.0
        lines = [f"## {matched_category}: evidence snapshot", "",
                 f"- Surveys: **{len(subset)}**",
                 f"- Average CSAT: **{avg:.2f}/5**",
                 f"- Low-CSAT records (1–2): **{len(subset_low)} ({low_pct:.1f}%)**",
                 f"- Distinct named customers in low-score records: **{_distinct_customer_count(subset_low)}**", ""]
        if not subset_low.empty:
            comments = subset_low.sort_values("SurveyDate", ascending=False)[["SurveyDate", "CustomerName", "CSATScore", "CustomerComment"]].head(8)
            lines.extend(["### Low-score customer comments to review", table(_records(comments, ["SurveyDate", "CustomerName", "CSATScore", "CustomerComment"]), ["SurveyDate", "CustomerName", "CSATScore", "CustomerComment"])])
            cat_insight = build_csat_insights(subset)
            if cat_insight["keyword_themes"]:
                lines.extend(["", "### Text signals (not verified root causes)", table(cat_insight["keyword_themes"], ["Theme signal", "Keyword matches"])])
            lines.extend(["", "### Suggested next step", f"Review the quoted feedback and validate the issue with operational data before calling it a root cause. Prioritise score-1/2 cases for follow-up."])
        else:
            lines.append("No low-CSAT records exist in this category for the selected range.")
        return "\n".join(lines)

    if any(term in q for term in ("flight", "airport", "site")) and any(term in q for term in ("low", "complaint", "issue", "affected", "impact", "alert", "worst", "most")):
        column = "FlightNumber" if "flight" in q else ("Airport" if "airport" in q else "Airport")
        if column not in low.columns or low.empty:
            return f"No low-CSAT records have usable {column} values in this period."
        grouped = low.groupby(column, dropna=False).agg(
            low_score_surveys=("CSATScore", "count"), average_csat=("CSATScore", "mean")
        ).reset_index().sort_values("low_score_surveys", ascending=False)
        grouped["average_csat"] = grouped["average_csat"].round(2)
        rows = [{"Flight / airport": str(row[column]), "Low-score surveys": int(row["low_score_surveys"]),
                 "Average CSAT": float(row["average_csat"])} for row in grouped.to_dict("records")]
        return "Low-CSAT records grouped by " + column + ":\n\n" + table(rows, ["Flight / airport", "Low-score surveys", "Average CSAT"])

    if any(term in q for term in ("how many surveys", "number of surveys", "total surveys", "survey count", "how many feedback", "total feedback")):
        return (f"There are **{metrics['survey_count']} surveys** in this range. Average CSAT: **{metrics['average_csat']:.2f}/5**; "
                f"positive CSAT (4–5): **{metrics['positive_rate_pct']:.1f}%**; low CSAT (1–2): **{metrics['low_score_count']} ({metrics['low_rate_pct']:.1f}%)**.")

    customer_count_terms = ("how many customers", "number of customers", "unique customers", "customer count", "customers submitted", "distinct customers")
    if any(term in q for term in customer_count_terms):
        names = frame[frame["CustomerName"].map(_is_known_name)]
        distinct = _distinct_customer_count(names)
        return (f"There are **{distinct} distinct named customer(s)** in the selected feedback records. "
                f"This is based on unique CustomerName values, not a verified customer ID. "
                f"Low-CSAT records represent **{metrics['customers_with_low_scores']} distinct named customer(s)**.")

    # Fall through to the more granular legacy deterministic query handler.
    return None
