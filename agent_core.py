from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import re
import json, os, smtplib, ssl
from email.message import EmailMessage
import pandas as pd
from insights_engine import build_csat_insights
from email_report import render_html_report
import requests
from config import (
    OLLAMA_URL, OLLAMA_MODEL, GMAIL_ADDRESS, GMAIL_APP_PASSWORD,
    REPORT_EMAIL_TO, REPORTS_DIR, LOGS_DIR, DRIVE_DOWNLOAD_URL, DRIVE_CACHE_FILE, GOOGLE_SERVICE_ACCOUNT_JSON
)

REQUIRED = {"SurveyDate", "StaffID", "StaffName", "Category", "CustomerComment", "CSATScore", "SurveyID"}

def required_columns():
    return REQUIRED

def _normalize_survey_dataframe(df, sheet_name="rowdata"):
    """Apply the same schema and type validation to Excel and Google Sheets data."""
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {sheet_name}: {', '.join(sorted(missing))}")
    # Google Sheets can return dates formatted according to spreadsheet locale;
    # format='mixed' accepts both ISO dates and locale-rendered date strings.
    df["SurveyDate"] = pd.to_datetime(df["SurveyDate"], errors="coerce", format="mixed").dt.date
    df["CSATScore"] = pd.to_numeric(df["CSATScore"], errors="coerce")
    df = df.dropna(subset=["SurveyDate", "CSATScore"])
    df["StaffID"] = df["StaffID"].fillna("").astype(str)
    df["StaffName"] = df["StaffName"].fillna("Unknown").astype(str)
    df["Category"] = df["Category"].fillna("Uncategorized").astype(str)
    # CustomerName was added for the feedback-form workflow. Keep older sources readable.
    if "CustomerName" not in df.columns:
        df["CustomerName"] = "Unknown Customer"
    df["CustomerName"] = df["CustomerName"].fillna("Unknown Customer").astype(str).str.strip()
    df.loc[df["CustomerName"].eq(""), "CustomerName"] = "Unknown Customer"
    df["CustomerComment"] = df["CustomerComment"].fillna("").astype(str)
    return df


def load_excel(source, sheet_name="rowdata"):
    """Load the expected worksheet from a path or a file-like object."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Excel file not found: {path}")
        excel_source = path
    else:
        # Streamlit UploadedFile and BytesIO are supported by pandas.read_excel.
        excel_source = source
    df = pd.read_excel(excel_source, sheet_name=sheet_name)
    return _normalize_survey_dataframe(df, sheet_name)


def load_google_sheet(url=None, sheet_name="rowdata"):
    """Read the live native Google Sheet through the service account / Sheets API.

    This avoids unauthenticated `/export?format=xlsx` downloads, which fail for
    private sheets and were the source of the dashboard 401 error.
    """
    from feedback_service import _sheets_service, spreadsheet_id_from_url

    spreadsheet_url = (url if url is not None else DRIVE_DOWNLOAD_URL).strip()
    spreadsheet_id = spreadsheet_id_from_url(spreadsheet_url)
    service = _sheets_service()
    safe_sheet_name = str(sheet_name).replace("'", "''")
    range_name = f"'{safe_sheet_name}'!A:Z"
    response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueRenderOption="FORMATTED_VALUE",
        dateTimeRenderOption="FORMATTED_STRING",
    ).execute()
    values = response.get("values", [])
    if not values or not any(str(v).strip() for v in values[0]):
        raise ValueError(f"Google Sheet tab '{sheet_name}' is empty or its header row is missing.")
    headers = [str(value).strip() for value in values[0]]
    if len(headers) != len(set(headers)):
        raise ValueError(f"Google Sheet tab '{sheet_name}' has duplicate column headers.")
    data_rows = []
    for row in values[1:]:
        row = list(row)
        if len(row) < len(headers):
            row += [None] * (len(headers) - len(row))
        data_rows.append(row[:len(headers)])
    df = pd.DataFrame(data_rows, columns=headers)
    return _normalize_survey_dataframe(df, sheet_name)


def google_download_url(url):
    """Convert Google Sheets/Drive share URLs into direct Excel download URLs."""
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    # Google Sheets: export the complete workbook as XLSX so pandas can select
    # the configured worksheet (normally `rowdata`) from the downloaded file.
    if host in {"docs.google.com", "sheets.google.com"}:
        match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", parsed.path)
        if match:
            return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=xlsx"

    # Google Drive file share links.
    match = re.search(r"/file/d/([A-Za-z0-9_-]+)", parsed.path)
    file_id = match.group(1) if match else None
    if not file_id and host.endswith("drive.google.com"):
        qs = parse_qs(parsed.query)
        file_id = (qs.get("id") or [None])[0]
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url


def download_google_drive_excel(url=None, target_path=None, timeout=45):
    """Download an Excel file or Google Sheets workbook. Link-based access only;
    private company files require Google Drive OAuth/API authentication.
    """
    url = (url if url is not None else DRIVE_DOWNLOAD_URL).strip()
    if not url:
        raise RuntimeError("Google Drive is the scheduled source, but DRIVE_DOWNLOAD_URL is not configured in .env.")
    # Private Google Drive/Sheets access can use a service-account JSON stored in
    # an environment variable or Streamlit secret. Share the source file with that
    # service account's email address. Public link downloads remain supported.
    if GOOGLE_SERVICE_ACCOUNT_JSON:
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaIoBaseDownload
            import io
            credentials_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
            credentials = Credentials.from_service_account_info(
                credentials_info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
            )
            parsed = urlparse(url)
            match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", parsed.path)
            if not match:
                match = re.search(r"/file/d/([A-Za-z0-9_-]+)", parsed.path)
            file_id = match.group(1) if match else (parse_qs(parsed.query).get("id") or [None])[0]
            if not file_id:
                raise ValueError("Could not identify the Google Drive file ID from DRIVE_DOWNLOAD_URL.")
            service = build("drive", "v3", credentials=credentials, cache_discovery=False)
            metadata = service.files().get(fileId=file_id, fields="id,name,mimeType").execute()
            if metadata.get("mimeType") == "application/vnd.google-apps.spreadsheet":
                request = service.files().export_media(
                    fileId=file_id,
                    mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                request = service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            content = buffer.getvalue()
        except Exception as exc:
            raise RuntimeError(f"Authenticated Google Drive download failed: {exc}") from exc
    else:
        download_url = google_download_url(url)
        response = requests.get(download_url, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        content = response.content
    # XLSX is a ZIP container and begins with PK; this catches HTML login/permission pages.
    if not content.startswith(b"PK"):
        raise RuntimeError(
            "Google did not return an Excel workbook. Confirm that the spreadsheet is accessible "
            "to the account running this app (for link-based access, enable suitable sharing). "
            "Private company files require Google Drive OAuth/API authentication."
        )
    target = Path(target_path or DRIVE_CACHE_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def get_available_dates(df):
    return sorted(df["SurveyDate"].dropna().unique().tolist())

def _ollama_analysis(comments, model):
    # Respect the local-model-only setup: never send comments to a hosted Ollama API.
    ollama_host = urlparse((OLLAMA_URL or "http://localhost:11434").strip()).hostname
    if ollama_host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Local Ollama only is enabled. Set OLLAMA_URL to http://localhost:11434; remote Ollama endpoints are not used.")
    prompt = f"""
You are a careful customer-experience analyst. Analyze only the supplied survey comments.
Return valid JSON only with keys: sentiment_summary, recurring_issues, positive_themes,
root_cause_hypotheses, recommended_actions.
For every hypothesis, clearly label it as a hypothesis, not a proven fact.
Do not invent facts, counts, scores, or staff performance explanations.
Keep the answer concise and actionable. Do not infer that a named staff member caused a complaint.
Comments (each prefixed with an ID):
{json.dumps(comments, ensure_ascii=False)}
"""
    response = requests.post(
        f"{OLLAMA_URL.rstrip('/')}/api/generate",
        json={"model": model or OLLAMA_MODEL, "prompt": prompt, "stream": False,
              "format": "json", "options": {"temperature": 0.1}},
        timeout=240
    )
    response.raise_for_status()
    body = response.json().get("response", "")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"sentiment_summary": body, "recurring_issues": [], "positive_themes": [],
                "root_cause_hypotheses": [], "recommended_actions": [],
                "warning": "Model response was not valid JSON; inspect raw summary."}

def _fallback_analysis(day_df):
    low = day_df[day_df["CSATScore"] <= 2]
    high = day_df[day_df["CSATScore"] >= 4]
    return {
        "sentiment_summary": f"{len(high)} surveys have CSAT 4–5; {len(low)} surveys have CSAT 1–2.",
        "recurring_issues": low.groupby("Category").size().sort_values(ascending=False).head(5).reset_index().rename(columns={0:"count"}).to_dict("records"),
        "positive_themes": ["Review high-scoring comments to identify service practices worth repeating."],
        "root_cause_hypotheses": ["Treat any possible cause as a hypothesis until operational data confirms it."],
        "recommended_actions": ["Review low-CSAT comments by category and investigate the highest-volume issue."]
    }

def analyze_day(df, selected_date, model=None, use_llm=True):
    """Analyze one date or an inclusive (start_date, end_date) date range."""
    if isinstance(selected_date, (tuple, list)):
        if len(selected_date) != 2:
            raise ValueError("Date range must contain a start date and an end date.")
        start_date, end_date = selected_date
        if start_date > end_date:
            raise ValueError("Start date must be on or before end date.")
        day_df = df[(df["SurveyDate"] >= start_date) & (df["SurveyDate"] <= end_date)].copy()
        report_date = str(start_date) if start_date == end_date else f"{start_date}_to_{end_date}"
        report_title_date = str(start_date) if start_date == end_date else f"{start_date} to {end_date}"
    else:
        day_df = df[df["SurveyDate"] == selected_date].copy()
        report_date = str(selected_date)
        report_title_date = str(selected_date)
    if day_df.empty:
        raise ValueError(f"No survey rows found for {report_title_date}")
    day_df["CSATScore"] = pd.to_numeric(day_df["CSATScore"], errors="coerce")
    day_df = day_df.dropna(subset=["CSATScore"])
    if ((day_df["CSATScore"] < 1) | (day_df["CSATScore"] > 5)).any():
        raise ValueError("CSATScore must be between 1 and 5.")
    count = int(len(day_df))
    avg = float(day_df["CSATScore"].mean())
    positive = float((day_df["CSATScore"] >= 4).mean() * 100)
    low_rate = float((day_df["CSATScore"] <= 2).mean() * 100)

    staff = (day_df.groupby(["StaffID", "StaffName"], dropna=False)
             .agg(survey_count=("SurveyID", "count"), average_csat=("CSATScore", "mean"),
                  min_csat=("CSATScore", "min"), max_csat=("CSATScore", "max"))
             .reset_index())
    # Ranking is shown with sample counts and a configurable minimum sample threshold in report.
    staff = staff.sort_values(["average_csat", "survey_count"], ascending=[True, False])
    category = (day_df.groupby("Category")
                .agg(survey_count=("SurveyID", "count"), average_csat=("CSATScore", "mean"))
                .reset_index().sort_values(["average_csat", "survey_count"], ascending=[True, False]))
    low_comments = day_df[day_df["CSATScore"] <= 2][["SurveyID", "Category", "CustomerComment"]]
    comments = [{"survey_id": r.SurveyID, "category": r.Category, "comment": r.CustomerComment}
                for r in day_df[["SurveyID", "Category", "CustomerComment"]].itertuples(index=False)]
    if use_llm:
        try:
            ai = _ollama_analysis(comments, model)
            ai["analysis_mode"] = "Local Ollama analysis"
        except Exception as exc:
            # Keep the operational report usable even when the local model is stopped
            # or unreachable (common when the admin app is hosted in the cloud).
            ai = _fallback_analysis(day_df)
            ai["analysis_mode"] = "Python fallback; local Ollama was unavailable."
            ai["warning"] = f"Local Ollama could not be reached: {type(exc).__name__}: {str(exc)[:240]}"
    else:
        ai = _fallback_analysis(day_df)
        ai["analysis_mode"] = "Python-only fallback; Ollama was not used."

    cx_insights = build_csat_insights(day_df)

    staff_records = []
    for r in staff.to_dict("records"):
        staff_records.append({
            "staff_id": str(r["StaffID"]), "staff_name": str(r["StaffName"]),
            "survey_count": int(r["survey_count"]), "average_csat": round(float(r["average_csat"]), 2),
            "min_csat": float(r["min_csat"]), "max_csat": float(r["max_csat"])
        })
    category_records = [{"category": str(r["Category"]), "survey_count": int(r["survey_count"]),
                         "average_csat": round(float(r["average_csat"]), 2)}
                        for r in category.to_dict("records")]
    min_avg = min(staff_records, key=lambda x: x["average_csat"])
    max_avg = max(staff_records, key=lambda x: x["average_csat"])
    payload = {
        "report_date": report_date,
        "report_period": report_title_date,
        "metrics": {"survey_count": count, "average_csat": round(avg, 2),
                    "positive_rate_pct": round(positive, 1), "low_rate_pct": round(low_rate, 1)},
        "staff_rankings": staff_records,
        "lowest_staff_average_csat": min_avg,
        "highest_staff_average_csat": max_avg,
        "category_summary": category_records,
        "cx_insights": cx_insights,
        "ai_analysis": ai,
        "data_quality_notes": [
            "Staff comparisons are based only on surveys in the selected report period.",
            "Show survey counts beside averages; one or two surveys are not enough for a robust performance conclusion.",
            "Survey feedback alone does not establish individual staff causality."
        ]
    }
    md = render_markdown(payload)
    payload["report_markdown"] = md
    return {"payload": payload, "report_markdown": md,
            "json_text": json.dumps(payload, ensure_ascii=False, indent=2),
            "metrics": payload["metrics"]}

def _bullets(value):
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append("- " + "; ".join(f"{k}: {v}" for k,v in item.items()))
            else:
                out.append(f"- {item}")
        return "\n".join(out) if out else "- No items returned."
    if isinstance(value, dict):
        return "\n".join(f"- **{k}:** {v}" for k,v in value.items())
    return f"- {value}" if value else "- No items returned."

def render_markdown(p):
    m = p["metrics"]
    low, high = p["lowest_staff_average_csat"], p["highest_staff_average_csat"]
    lines = [
        f"# Customer Feedback Report — {p.get('report_period', p['report_date'])}", "",
        "## KPI Summary", "",
        f"- Survey count: **{m['survey_count']}**",
        f"- Average CSAT: **{m['average_csat']}/5**",
        f"- Positive CSAT (4–5): **{m['positive_rate_pct']}%**",
        f"- Low CSAT (1–2): **{m['low_rate_pct']}%**", "",
        "## Staff CSAT Comparison", "",
        f"- Lowest average: **{low['staff_name']} ({low['staff_id']})** — {low['average_csat']}/5 across {low['survey_count']} survey(s).",
        f"- Highest average: **{high['staff_name']} ({high['staff_id']})** — {high['average_csat']}/5 across {high['survey_count']} survey(s).",
        "",
        "| Staff ID | Staff name | Surveys | Avg CSAT | Min | Max |",
        "|---|---|---:|---:|---:|---:|"
    ]
    for s in p["staff_rankings"]:
        lines.append(f"| {s['staff_id']} | {s['staff_name']} | {s['survey_count']} | {s['average_csat']} | {s['min_csat']} | {s['max_csat']} |")
    lines += ["", "## Category Summary", "", "| Category | Surveys | Avg CSAT |", "|---|---:|---:|"]
    for c in p["category_summary"]:
        lines.append(f"| {c['category']} | {c['survey_count']} | {c['average_csat']} |")
    ai = p["ai_analysis"]
    lines += ["", "## Feedback Analysis", "", "### Sentiment summary", "", str(ai.get("sentiment_summary", "Not available.")),
              "", "### Recurring issues", "", _bullets(ai.get("recurring_issues")),
              "", "### Positive themes", "", _bullets(ai.get("positive_themes")),
              "", "### Root-cause hypotheses (not confirmed facts)", "", _bullets(ai.get("root_cause_hypotheses")),
              "", "### Recommended actions", "", _bullets(ai.get("recommended_actions")),
              ""]
    insights = p.get("cx_insights") or {}
    insight_metrics = insights.get("metrics", {})
    if insight_metrics:
        lines += ["## Executive Summary & Customer Impact", "",
                  str(insights.get("executive_summary", "No summary available.")), "",
                  f"- Critical score-1 cases: **{insight_metrics.get('critical_score1_count', 0)}**",
                  f"- Distinct named customers represented in low-score cases: **{insight_metrics.get('customers_with_low_scores', 0)}**",
                  ""]
    lines += ["## Alerts & Recommended Actions", ""]
    alerts = insights.get("alerts", [])
    if alerts:
        for alert in alerts:
            lines += [f"### [{alert.get('severity', 'INFO')}] {alert.get('title', 'Alert')}",
                      f"- **Signal:** {alert.get('metric', '')}",
                      f"- **What it means:** {alert.get('detail', '')}",
                      f"- **Recommended action:** {alert.get('recommendation', '')}", ""]
    else:
        lines += ["No rule-based CSAT alerts were triggered for this period.", ""]
    categories_insight = insights.get("category_summary", [])
    if categories_insight:
        lines += ["## Category Impact Table", "",
                  "| Category | Surveys | Average CSAT | Low CSAT (1-2) | Low CSAT % | Named customers impacted |",
                  "|---|---:|---:|---:|---:|---:|"]
        for row in categories_insight[:15]:
            lines.append(f"| {row.get('Category', '')} | {row.get('Surveys', 0)} | {row.get('Average CSAT', 0)} | {row.get('Low CSAT (1-2)', 0)} | {row.get('Low CSAT %', 0)}% | {row.get('Named customers impacted', 0)} |")
        lines.append("")
    themes = insights.get("keyword_themes", [])
    if themes:
        lines += ["## Feedback Text Signals", "",
                  "These are keyword-based signals from low-score comments, not confirmed root causes.", "",
                  "| Theme signal | Keyword matches |", "|---|---:|"]
        for row in themes[:10]:
            lines.append(f"| {row.get('Theme signal', '')} | {row.get('Keyword matches', 0)} |")
        lines.append("")
    lines += ["## Interpretation note", "",
              "Customer impact counts use distinct non-empty CustomerName values, not a verified customer identifier. Category/theme patterns are signals to investigate, not proof of root cause.",
              "Staff rankings are descriptive and based on the available survey sample only. They should not be used as a standalone employee-performance judgment.",
              ""]
    return "\n".join(lines)

def save_report(result, reports_dir=REPORTS_DIR):
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    d = result["payload"]["report_date"]
    md_path = reports_dir / f"customer_feedback_{d}.md"
    json_path = reports_dir / f"customer_feedback_{d}.json"
    md_path.write_text(result["report_markdown"], encoding="utf-8")
    json_path.write_text(result["json_text"], encoding="utf-8")
    html_path = reports_dir / f"customer_feedback_{d}.html"
    html_path.write_text(render_html_report(result["payload"]), encoding="utf-8")
    return md_path

def send_gmail(recipient, subject, body, html_body=None):
    sender = GMAIL_ADDRESS
    password = GMAIL_APP_PASSWORD.replace(" ", "")
    if not sender or not password:
        raise RuntimeError("Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env or Streamlit secrets first.")
    if not recipient or "@" not in recipient:
        raise ValueError("Enter a valid recipient email address.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    # Keep a plain-text alternative for clients that cannot render HTML.
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as server:
        server.login(sender, password)
        server.send_message(msg)

def get_last_processed_date(state_path=None):
    state_path = Path(state_path or (LOGS_DIR / "state.json"))
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8")).get("last_successful_date")
    except Exception:
        return None

def set_last_processed_date(day, state_path=None):
    state_path = Path(state_path or (LOGS_DIR / "state.json"))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"last_successful_date": str(day),
                                      "updated_at": datetime.now().isoformat(timespec="seconds")},
                                     indent=2), encoding="utf-8")
