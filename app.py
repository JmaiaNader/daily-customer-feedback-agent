from pathlib import Path
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from agent_core import (
    load_excel, load_google_sheet, analyze_day, get_available_dates, send_gmail,
    save_report, get_last_processed_date, set_last_processed_date,
    required_columns
)
from config import (BASE_DIR, DATA_FILE, REPORTS_DIR, DRIVE_DOWNLOAD_URL, ENABLE_BACKGROUND_SCHEDULER,
                    SCHEDULER_TIMEZONE, SHEET_NAME, RECIPIENTS_SPREADSHEET_URL)
from scheduler_service import (load_schedule_config, save_schedule_config, load_scheduler_status,
                               load_recipient_lists, save_recipient_lists, _validate_recipient_list,
                               run_scheduled_job, start_background_scheduler)
from chat_assistant import answer_question, is_report_request
from insights_engine import build_csat_insights, prepare_insight_frame
from email_report import render_html_report
from datetime import time as dt_time


st.set_page_config(page_title="Daily Customer Feedback Agent", page_icon="📊", layout="wide")

# This is the private administration dashboard. Access restriction is configured
# in Streamlit Community Cloud sharing settings, not with an in-app password.
st.title("📊 Daily Customer Feedback Analysis Agent")
st.caption("Google Sheets → Python analytics → optional local Ollama → Gmail, with configurable report scheduling")
flash_message = st.session_state.pop("admin_flash_message", None)
if flash_message:
    st.success(flash_message)
BACKGROUND_SCHEDULER_RUNNING = start_background_scheduler()

_DEFAULT_APP_SETTINGS = {
    "source": "Google Sheets (live data)",
    "drive_url": DRIVE_DOWNLOAD_URL,
    "sheet": SHEET_NAME or "rowdata",
    "model": "gemma3:4b",
    "use_llm": True,
}
if "app_settings" not in st.session_state:
    st.session_state["app_settings"] = _DEFAULT_APP_SETTINGS.copy()

with st.sidebar:
    st.header("Navigation")
    page = st.radio(
        "Open page",
        ["Dashboard", "Data preview", "Chat assistant", "Settings", "Scheduler", "How to use"],
        key="admin_page_navigation",
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("Feedback submissions are handled by the separate participant form.")

app_settings = st.session_state["app_settings"]
source = app_settings.get("source", _DEFAULT_APP_SETTINGS["source"])
drive_url = app_settings.get("drive_url", DRIVE_DOWNLOAD_URL)
sheet = app_settings.get("sheet", SHEET_NAME or "rowdata")
model = app_settings.get("model", "gemma3:4b")
use_llm = bool(app_settings.get("use_llm", True))


def read_source(uploaded_file=None):
    if source == "Laptop (test upload)":
        if uploaded_file is None:
            st.error("Upload an Excel file from your laptop first.")
            return None
        try:
            return load_excel(uploaded_file, sheet_name=sheet)
        except Exception as e:
            st.error(f"Could not read the uploaded Excel file: {e}")
            return None
    if not drive_url.strip():
        st.error("Configure DRIVE_DOWNLOAD_URL in Settings or Streamlit Secrets.")
        return None
    try:
        return load_google_sheet(drive_url, sheet_name=sheet)
    except Exception as e:
        st.error(f"Could not read Google Sheet: {e}")
        st.info("Check that DRIVE_DOWNLOAD_URL points to a native Google Sheet, the service-account credentials are correct, and the sheet is shared with the service-account email as Editor.")
        return None


def render_ai_interpretation(ai_result, key_prefix="ai"):
    """Render optional local-model commentary and make fallback status explicit."""
    if not ai_result:
        return
    with st.expander("AI interpretation of feedback comments", expanded=True):
        mode = ai_result.get("analysis_mode", "Python evidence summary")
        st.caption(f"Analysis mode: {mode}")
        if ai_result.get("warning"):
            st.info(ai_result["warning"] + " The evidence-based Python insights below are still available.")
        st.markdown("**Sentiment summary**")
        st.write(ai_result.get("sentiment_summary", "No summary returned."))
        for title, field in [
            ("Recurring issue signals", "recurring_issues"),
            ("Positive themes", "positive_themes"),
            ("Root-cause hypotheses to validate", "root_cause_hypotheses"),
            ("Recommended actions", "recommended_actions"),
        ]:
            value = ai_result.get(field, [])
            if not value:
                continue
            st.markdown(f"**{title}**")
            if isinstance(value, list) and value and isinstance(value[0], dict):
                st.dataframe(pd.DataFrame(value), use_container_width=True, hide_index=True)
            elif isinstance(value, list):
                st.markdown("\n".join(f"- {item}" for item in value))
            else:
                st.write(value)
        st.caption("AI/root-cause statements are hypotheses to check against original feedback and operational data, not proven causes.")


def render_insights_section(df, key_prefix="insights"):
    """Shared polished insight report used by Dashboard and Chat assistant pages."""
    try:
        import plotly.express as px
    except ImportError:
        st.error("Interactive charts require Plotly. Add plotly to requirements.txt and redeploy.")
        return build_csat_insights(df)

    frame = prepare_insight_frame(df)
    insight = build_csat_insights(frame)
    metrics = insight["metrics"]
    if not metrics.get("survey_count"):
        st.info("No valid CSAT feedback is available for this date range.")
        return insight

    st.markdown("### Executive summary")
    st.info(insight["executive_summary"])
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Surveys", f"{metrics['survey_count']:,}")
    k2.metric("Average CSAT", f"{metrics['average_csat']:.2f}/5")
    k3.metric("Positive (4–5)", f"{metrics['positive_rate_pct']:.1f}%")
    k4.metric("Low CSAT (1–2)", f"{metrics['low_score_count']:,}", delta=f"{metrics['low_rate_pct']:.1f}% of surveys", delta_color="inverse")
    k5.metric("Named customers impacted", f"{metrics['customers_with_low_scores']:,}", help="Distinct non-empty CustomerName values among low-score records; names are not a verified customer ID.")

    st.markdown("### Alerts and action priorities")
    if insight["alerts"]:
        severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}
        for alert in sorted(insight["alerts"], key=lambda item: severity_rank.get(item["severity"], 9)):
            msg = f"**{alert['title']}**\n\n**Signal:** {alert['metric']}\n\n{alert['detail']}\n\n**Recommended action:** {alert['recommendation']}"
            if alert["severity"] in {"CRITICAL", "HIGH"}:
                st.error(f"🚨 **{alert['severity']}** — {msg}")
            elif alert["severity"] == "MEDIUM":
                st.warning(f"⚠️ **{alert['severity']}** — {msg}")
            else:
                st.info(f"ℹ️ **{alert['severity']}** — {msg}")
    else:
        st.success("No rule-based CSAT alerts were triggered for this date range.")

    st.markdown("### Performance and customer-impact charts")
    score_df = pd.DataFrame(insight["score_distribution"])
    trend_df = pd.DataFrame(insight["daily_trend"])
    left, right = st.columns(2)
    with left:
        fig = px.bar(score_df, x="CSAT score", y="Surveys", text="Surveys", color="CSAT score",
                     category_orders={"CSAT score": [1, 2, 3, 4, 5]}, title="CSAT score distribution",
                     color_continuous_scale="RdYlGn")
        fig.update_layout(template="plotly_white", height=320, margin=dict(l=10, r=10, t=55, b=10), coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_score_distribution")
    with right:
        if not trend_df.empty:
            fig = px.line(trend_df, x="Date", y="Average CSAT", markers=True,
                          hover_data=["Surveys", "Low CSAT (1-2)"], title="CSAT trend by date")
            fig.update_yaxes(range=[1, 5], dtick=1)
            fig.update_layout(template="plotly_white", height=320, margin=dict(l=10, r=10, t=55, b=10))
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_csat_trend")
        else:
            st.info("No valid survey dates are available for a trend chart.")

    category_df = pd.DataFrame(insight["category_summary"])
    staff_df = pd.DataFrame(insight["staff_summary"])
    c1, c2 = st.columns(2)
    with c1:
        if not category_df.empty:
            category_chart = category_df.sort_values("Low CSAT (1-2)", ascending=True)
            fig = px.bar(category_chart, x="Low CSAT (1-2)", y="Category", orientation="h",
                         text="Low CSAT (1-2)", hover_data=["Surveys", "Average CSAT", "Named customers impacted"],
                         title="Issue categories affecting low CSAT", color="Low CSAT (1-2)", color_continuous_scale="OrRd")
            fig.update_layout(template="plotly_white", height=max(320, 40 * len(category_chart)), margin=dict(l=10, r=10, t=55, b=10), coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_category_impact")
    with c2:
        if not staff_df.empty:
            staff_chart = staff_df.sort_values("Average CSAT", ascending=True)
            fig = px.bar(staff_chart, x="Average CSAT", y="Staff name", orientation="h", text="Average CSAT",
                         hover_data=["Staff ID", "Surveys", "Low CSAT (1-2)", "Low CSAT %"],
                         title="Staff CSAT (survey volume shown)", color="Average CSAT", color_continuous_scale="RdYlGn", range_color=[1, 5])
            fig.update_xaxes(range=[1, 5])
            fig.update_layout(template="plotly_white", height=max(320, 40 * len(staff_chart)), margin=dict(l=10, r=10, t=55, b=10), coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_staff_csat")

    with st.expander("Category detail table", expanded=True):
        st.dataframe(category_df, use_container_width=True, hide_index=True)
    with st.expander("Staff comparison table", expanded=False):
        st.dataframe(staff_df, use_container_width=True, hide_index=True)
        st.caption("Staff comparisons are descriptive. Always consider sample size; scores alone do not prove causality.")
    with st.expander("Customer recovery queue", expanded=False):
        queue = pd.DataFrame(insight["recovery_queue"])
        if queue.empty:
            st.success("No low-CSAT recovery cases in this period.")
        else:
            st.dataframe(queue, use_container_width=True, hide_index=True, height=min(480, 38 + 36 * min(len(queue), 10)))
            st.download_button("Download recovery queue (CSV)", queue.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"customer_recovery_queue_{key_prefix}.csv", mime="text/csv", key=f"{key_prefix}_download_recovery")
    with st.expander("Feedback text signals", expanded=False):
        themes = pd.DataFrame(insight["keyword_themes"])
        if themes.empty:
            st.info("No configured keyword themes were found in the low-score comments. Read the original comments for context.")
        else:
            st.dataframe(themes, use_container_width=True, hide_index=True)
        st.caption("These theme matches are transparent keyword signals, not an LLM judgment or a confirmed root cause.")

    with st.expander("Recommended actions and interpretation notes", expanded=False):
        for action in insight["recommendations"]:
            st.markdown(f"- {action}")
        for note in insight["data_quality_notes"]:
            st.caption(f"• {note}")
    return insight


if page == "Dashboard":
    st.subheader("Run an analysis")
    uploaded_file = None
    if source == "Laptop (test upload)":
        uploaded_file = st.file_uploader("Choose an Excel file from your laptop", type=["xlsx", "xls"], key="desktop_excel_upload")
        st.caption("Desktop uploads are for manual testing and do not change the Scheduler's Google Sheets source.")
    else:
        st.caption("The app will load the configured native Google Sheet through the service account.")
    if st.button("Load data", type="secondary"):
        df = read_source(uploaded_file)
        if df is not None:
            st.session_state["data"] = df
            st.session_state["loaded_source"] = source
            st.session_state.pop("last_result", None)
            st.session_state.pop("last_selected", None)
            st.success(f"Loaded {len(df)} survey rows from {source}.")
    df = st.session_state.get("data")
    if df is not None:
        missing = required_columns() - set(df.columns)
        if missing:
            st.error(f"Missing required columns: {', '.join(sorted(missing))}")
        else:
            dates = get_available_dates(df)
            if not dates:
                st.warning("No valid SurveyDate values found.")
            else:
                c_start, c_end = st.columns(2)
                start_date = c_start.date_input("Start date", value=dates[0], min_value=dates[0], max_value=dates[-1])
                end_date = c_end.date_input("End date", value=dates[-1], min_value=dates[0], max_value=dates[-1])
                st.caption("Choose a date range for manual analysis. The Scheduler page has its own date-range setting.")
                if start_date > end_date:
                    st.error("Start date must be on or before end date.")
                elif st.button("Analyze selected date range", type="primary"):
                    with st.spinner("Analyzing survey data..."):
                        try:
                            result = analyze_day(df, (start_date, end_date), model=model, use_llm=use_llm)
                            st.session_state["last_result"] = result
                            st.session_state["last_selected"] = (start_date, end_date)
                        except Exception as e:
                            st.error(f"Analysis failed: {e}")
                result = st.session_state.get("last_result")
                if result and st.session_state.get("last_selected") == (start_date, end_date):
                    analysis_df = df[(df["SurveyDate"] >= start_date) & (df["SurveyDate"] <= end_date)].copy()
                    st.subheader(f"Customer experience report: {result['payload'].get('report_period', result['payload']['report_date'])}")
                    render_insights_section(analysis_df, key_prefix="dashboard")
                    render_ai_interpretation(result["payload"].get("ai_analysis"), key_prefix="dashboard_ai")
                    st.divider()
                    st.subheader("Styled HTML email report preview")
                    st.caption("This preview mirrors the formatted email, including KPI cards, colored alerts, email-safe charts, tables and recommended actions.")
                    with st.expander("Preview formatted email", expanded=True):
                        components.html(render_html_report(result["payload"]), height=1050, scrolling=True)
                    st.markdown("Download the plain-text/Markdown and structured versions below, or send the styled HTML report by Gmail.")
                    safe_period = result["payload"]["report_date"]
                    st.download_button("Download report (.md)", result["report_markdown"], file_name=f"customer_feedback_{safe_period}.md")
                    st.download_button("Download structured JSON", result["json_text"], file_name=f"customer_feedback_{safe_period}.json", mime="application/json")
                    if st.button("Save report locally"):
                        path = save_report(result, REPORTS_DIR)
                        st.success(f"Saved: {path}")
                    st.divider()
                    st.subheader("Review before sending")
                    st.caption("The report above is the exact content that will be sent. Review it before confirming. Desktop-loaded data is for testing; the Scheduler always reads Google Sheets.")
                    recipient = st.text_input("Send report to", placeholder="you@gmail.com", key="recipient")
                    confirm_send = st.checkbox("I reviewed the report and want to send it by Gmail.")
                    if st.button("Send reviewed report with Gmail", disabled=not confirm_send):
                        try:
                            send_gmail(recipient, f"Customer Feedback Report — {result['payload'].get('report_period', result['payload']['report_date'])}", result["report_markdown"], html_body=render_html_report(result["payload"]))
                            st.success("Email sent.")
                        except Exception as e:
                            st.error(f"Email failed: {e}")
                    st.warning("Staff ranking uses only the selected date range. Small sample sizes can make rankings unstable.")
    else:
        st.info("Choose Google Sheets for the default data source, or Laptop for a manual test upload, then click **Load data**.")

elif page == "Data preview":
    st.subheader("Excel data preview — rowdata")
    df = st.session_state.get("data")
    if df is not None:
        view = df.copy()
        dates = get_available_dates(view)
        if dates:
            d1, d2 = st.columns(2)
            filter_start = d1.date_input("Filter from", value=dates[0], key="table_filter_start")
            filter_end = d2.date_input("Filter to", value=dates[-1], key="table_filter_end")
            if filter_start > filter_end:
                st.error("Filter start date must be on or before filter end date.")
                view = view.iloc[0:0]
            else:
                view = view[(view["SurveyDate"] >= filter_start) & (view["SurveyDate"] <= filter_end)]
        f1, f2, f3 = st.columns(3)
        if "Category" in view.columns:
            cats = ["All"] + sorted(view["Category"].dropna().astype(str).unique().tolist())
            chosen_cat = f1.selectbox("Category", cats)
            if chosen_cat != "All":
                view = view[view["Category"].astype(str) == chosen_cat]
        if "StaffName" in view.columns:
            staff_names = ["All"] + sorted(view["StaffName"].dropna().astype(str).unique().tolist())
            chosen_staff = f2.selectbox("Staff", staff_names)
            if chosen_staff != "All":
                view = view[view["StaffName"].astype(str) == chosen_staff]
        if "CSATScore" in view.columns:
            score_options = ["All", "Low (1–2)", "Neutral (3)", "High (4–5)"]
            chosen_score = f3.selectbox("CSAT group", score_options)
            if chosen_score == "Low (1–2)":
                view = view[view["CSATScore"] <= 2]
            elif chosen_score == "Neutral (3)":
                view = view[view["CSATScore"] == 3]
            elif chosen_score == "High (4–5)":
                view = view[view["CSATScore"] >= 4]
        st.caption(f"Showing {len(view)} of {len(df)} rows.")
        st.dataframe(view, use_container_width=True, hide_index=True)
        csv_bytes = view.copy()
        if "SurveyDate" in csv_bytes.columns:
            csv_bytes["SurveyDate"] = csv_bytes["SurveyDate"].astype(str)
        st.download_button("Export filtered rows to CSV", data=csv_bytes.to_csv(index=False).encode("utf-8-sig"),
                           file_name="rowdata_filtered.csv", mime="text/csv")
        from io import BytesIO
        xlsx_buffer = BytesIO()
        with pd.ExcelWriter(xlsx_buffer, engine="openpyxl") as writer:
            export_df = view.copy()
            if "SurveyDate" in export_df.columns:
                export_df["SurveyDate"] = export_df["SurveyDate"].astype(str)
            export_df.to_excel(writer, index=False, sheet_name="rowdata")
        st.download_button("Export filtered rows to Excel", data=xlsx_buffer.getvalue(),
                           file_name="rowdata_filtered.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("Load the data on the Dashboard page first.")

elif page == "Chat assistant":
    st.subheader("CSAT Data Assistant")
    st.caption("Ask questions about real feedback. Python computes counts, customer impact, charts and alerts; local Ollama can interpret otherwise unsupported questions when it is reachable from this machine. Report emails always require review and explicit confirmation.")

    refresh_col, source_col = st.columns([1, 3])
    with refresh_col:
        refresh_chat_data = st.button("Refresh live feedback data", type="primary", key="refresh_assistant_data")
    with source_col:
        st.caption(f"Live data source: {drive_url or 'not configured'} · Worksheet: {sheet}")
    if refresh_chat_data:
        try:
            st.session_state["assistant_df"] = load_google_sheet(drive_url, sheet_name=sheet)
            st.session_state["assistant_data_loaded_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state["assistant_messages"] = []
            st.session_state.pop("pending_report", None)
            st.session_state.pop("assistant_ai_interpretation", None)
            st.success(f"Loaded {len(st.session_state['assistant_df'])} feedback rows from the live Google Sheet.")
        except Exception as exc:
            st.error(f"Could not load live feedback: {exc}")

    assistant_df = st.session_state.get("assistant_df")
    if assistant_df is None:
        st.info("Click **Refresh live feedback data** to load the latest submissions before asking questions.")
    else:
        if st.session_state.get("assistant_data_loaded_at"):
            st.caption(f"Data last refreshed: {st.session_state['assistant_data_loaded_at']} · {len(assistant_df)} rows")
        available_dates = get_available_dates(assistant_df)
        if not available_dates:
            st.warning("No valid survey dates are available in the live data.")
        else:
            date_left, date_right = st.columns(2)
            chat_start = date_left.date_input("Query/report from", value=available_dates[0], min_value=available_dates[0], max_value=available_dates[-1], key="chat_range_start")
            chat_end = date_right.date_input("Query/report to", value=available_dates[-1], min_value=available_dates[0], max_value=available_dates[-1], key="chat_range_end")
            if chat_start > chat_end:
                st.error("The start date must be on or before the end date.")
            else:
                chat_data = assistant_df[(assistant_df["SurveyDate"] >= chat_start) & (assistant_df["SurveyDate"] <= chat_end)].copy()
                st.caption(f"Questions will use {len(chat_data)} record(s) from {chat_start} through {chat_end}.")
                render_insights_section(chat_data, key_prefix="chat")

                ai_col, ai_info = st.columns([1, 3])
                with ai_col:
                    run_comment_ai = st.button("Generate local Ollama analysis", key="chat_generate_local_ai", disabled=not use_llm,
                                               help="Uses the configured local Ollama model only when it is reachable from the machine running this app.")
                with ai_info:
                    st.caption("The charts, alert counts and customer-impact metrics are calculated in Python. Optional Ollama commentary analyses feedback themes; on Streamlit Cloud, your laptop's localhost is not reachable.")
                if run_comment_ai:
                    with st.spinner("Asking the configured Ollama model to interpret comments..."):
                        try:
                            ai_result = analyze_day(assistant_df, (chat_start, chat_end), model=model, use_llm=True)
                            st.session_state["assistant_ai_interpretation"] = {
                                "range": (str(chat_start), str(chat_end)),
                                "analysis": ai_result["payload"].get("ai_analysis", {}),
                            }
                        except Exception as exc:
                            st.error(f"Could not generate commentary: {exc}")
                saved_ai = st.session_state.get("assistant_ai_interpretation")
                if saved_ai and saved_ai.get("range") == (str(chat_start), str(chat_end)):
                    render_ai_interpretation(saved_ai.get("analysis"), key_prefix="chat_ai")

                with st.form("feedback_chat_form", clear_on_submit=True):
                    user_question = st.text_input("Ask a question", placeholder="e.g. Which customers need recovery? What alerts need action? Why did CSAT decline? Prepare a report for Managers.")
                    ask_clicked = st.form_submit_button("Ask assistant", type="primary")
                if ask_clicked:
                    if not user_question.strip():
                        st.warning("Enter a question first.")
                    elif chat_data.empty:
                        st.warning("There are no feedback records in this date range.")
                    else:
                        wants_report, explicitly_asks_send = is_report_request(user_question)
                        if wants_report:
                            try:
                                report_result = analyze_day(assistant_df, (chat_start, chat_end), model=model, use_llm=use_llm)
                                st.session_state["pending_report"] = {
                                    "result": report_result,
                                    "start": str(chat_start),
                                    "end": str(chat_end),
                                    "send_requested": explicitly_asks_send,
                                }
                                reply = (f"I prepared a report for **{chat_start} to {chat_end}** using Python analytics. "
                                         "It has **not** been emailed. Review the preview below, choose a saved recipient list, "
                                         "and confirm sending when ready.")
                            except Exception as exc:
                                reply = f"I could not prepare the report: {exc}"
                        else:
                            reply = answer_question(chat_data, user_question, model=model, use_llm=use_llm)
                        messages = st.session_state.setdefault("assistant_messages", [])
                        messages.append({"role": "user", "content": user_question})
                        messages.append({"role": "assistant", "content": reply})

                for message in st.session_state.get("assistant_messages", []):
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])

                pending = st.session_state.get("pending_report")
                if pending:
                    st.divider()
                    st.subheader("Report preview and email confirmation")
                    result = pending["result"]
                    with st.expander("Preview the formatted email report", expanded=True):
                        components.html(render_html_report(result["payload"]), height=1050, scrolling=True)
                    recipient_lists = {}
                    recipient_storage_error = None
                    try:
                        recipient_lists = load_recipient_lists()
                    except Exception as exc:
                        recipient_storage_error = str(exc)
                    if recipient_storage_error:
                        st.error(f"Could not load saved recipient lists: {recipient_storage_error}")
                    elif not recipient_lists:
                        st.warning("No saved recipient lists are available yet. Create one below after configuring the private recipient-list spreadsheet.")
                    else:
                        list_names = list(recipient_lists.keys())
                        requested_list = next((name for name in list_names if name.casefold() in " ".join(m["content"] for m in st.session_state.get("assistant_messages", [])[-2:]).casefold()), None)
                        default_idx = list_names.index(requested_list) if requested_list in list_names else 0
                        selected_recipients = st.selectbox("Recipient list", list_names, index=default_idx, key="report_recipient_list")
                        to_addresses = recipient_lists.get(selected_recipients, [])
                        st.caption(f"Recipients ({len(to_addresses)}): " + (", ".join(to_addresses) if to_addresses else "This list is empty."))
                        reviewed = st.checkbox("I reviewed the report and confirm that it should be emailed to this list.", key="confirm_chat_report_send")
                        if st.button("Send report by Gmail", type="primary", disabled=(not reviewed or not to_addresses), key="send_chat_report"):
                            try:
                                period = result["payload"].get("report_period", result["payload"]["report_date"])
                                send_gmail(", ".join(to_addresses), f"Customer Feedback Report — {period}", result["report_markdown"], html_body=render_html_report(result["payload"]))
                                st.session_state["admin_flash_message"] = f"Report emailed to the '{selected_recipients}' list."
                                st.session_state["last_sent_report_period"] = period
                                st.session_state.pop("pending_report", None)
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Email failed: {exc}")

elif page == "Settings":
    st.header("Settings")
    st.caption("Configure this admin session and manage saved report-recipient lists. Credentials are supplied through local .env or Streamlit Cloud Secrets.")

    st.subheader("Application settings")
    with st.form("application_settings_form"):
        source_options = ["Google Sheets (live data)", "Laptop (test upload)"]
        source_index = source_options.index(source) if source in source_options else 0
        new_source = st.selectbox(
            "Data source",
            source_options,
            index=source_index,
            help="Google Sheets is the live source. Laptop upload is for manual testing only.",
            key="settings_source_choice",
        )
        new_drive_url = st.text_input(
            "Google Sheets URL",
            value=drive_url,
            help="Use the same native Google Sheet that receives participant submissions.",
            key="settings_drive_url",
        )
        new_sheet = st.text_input("Worksheet tab", value=sheet, key="settings_sheet_name")
        new_model = st.text_input("Local Ollama model", value=model, key="settings_ollama_model")
        new_use_llm = st.toggle("Use local Ollama for comment analysis", value=use_llm, key="settings_use_local_ollama")
        save_app_settings = st.form_submit_button("Save application settings", type="primary")
        if save_app_settings:
            if not new_sheet.strip():
                st.error("Worksheet tab name cannot be empty.")
            elif new_source == "Google Sheets (live data)" and not new_drive_url.strip():
                st.error("Enter the Google Sheets URL.")
            else:
                st.session_state["app_settings"] = {
                    "source": new_source,
                    "drive_url": new_drive_url.strip(),
                    "sheet": new_sheet.strip(),
                    "model": new_model.strip() or "gemma3:4b",
                    "use_llm": bool(new_use_llm),
                }
                st.session_state.pop("data", None)
                st.session_state.pop("last_result", None)
                st.session_state.pop("last_selected", None)
                st.session_state.pop("assistant_df", None)
                st.session_state.pop("pending_report", None)
                st.session_state["admin_flash_message"] = "Application settings saved for this session. Reload data on the Dashboard or Chat assistant page to use the updated values."
                st.rerun()

    st.caption("Application settings are held for the current Streamlit session. For permanent cloud configuration, update the relevant values in the admin app's Streamlit Secrets.")
    st.divider()

    st.subheader("Manage report recipient lists")
    st.caption("Create, update or delete the named email lists used for manual and scheduled reports. Recipients do not need access to either spreadsheet.")
    if not RECIPIENTS_SPREADSHEET_URL:
        st.warning(
            "Persistent online list management is not configured yet. Create a separate PRIVATE Google spreadsheet for recipient emails, "
            "share it with the service account as Editor, then set RECIPIENTS_SPREADSHEET_URL in Streamlit Secrets. "
            "Do not store recipient emails in the feedback spreadsheet if that workbook is publicly viewable."
        )
    try:
        current_lists = load_recipient_lists()
    except Exception as exc:
        current_lists = {}
        st.error(f"Could not read saved recipient lists: {exc}")
    if current_lists:
        list_rows = [{"List name": name, "Number of addresses": len(addresses), "Addresses": ", ".join(addresses)}
                     for name, addresses in current_lists.items()]
        st.dataframe(pd.DataFrame(list_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No named recipient lists are currently saved.")

    with st.form("recipient_list_save_form"):
        st.markdown("**Create a new list or update an existing one**")
        list_name_input = st.text_input("List name", placeholder="e.g. Operations, Managers, CX Leadership")
        list_emails_input = st.text_area("Email addresses", placeholder="One email per line, or separate addresses with commas", height=100)
        save_list_clicked = st.form_submit_button("Save recipient list", type="primary", disabled=not bool(RECIPIENTS_SPREADSHEET_URL))
        if save_list_clicked:
            try:
                clean_name, clean_emails = _validate_recipient_list(list_name_input, list_emails_input)
                updated_lists = dict(load_recipient_lists())
                updated_lists[clean_name] = clean_emails
                save_recipient_lists(updated_lists)
                st.session_state["admin_flash_message"] = f"Saved recipient list '{clean_name}' with {len(clean_emails)} address(es)."
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save recipient list: {exc}")

    with st.form("recipient_list_delete_form"):
        st.markdown("**Delete a saved list**")
        deletable_names = list(current_lists.keys())
        selected_to_delete = st.selectbox("List to delete", deletable_names if deletable_names else ["No lists available"], disabled=(not deletable_names or not bool(RECIPIENTS_SPREADSHEET_URL)))
        delete_list_clicked = st.form_submit_button("Delete selected list", disabled=(not deletable_names or not bool(RECIPIENTS_SPREADSHEET_URL)))
        if delete_list_clicked and selected_to_delete in current_lists:
            try:
                updated_lists = dict(current_lists)
                del updated_lists[selected_to_delete]
                save_recipient_lists(updated_lists)
                st.session_state["admin_flash_message"] = f"Deleted recipient list '{selected_to_delete}'."
                st.rerun()
            except Exception as exc:
                st.error(f"Could not delete recipient list: {exc}")

elif page == "Scheduler":
    st.subheader("Scheduled report configuration")
    st.caption(f"Schedule timezone: {SCHEDULER_TIMEZONE}. The scheduler always reads Google Sheets; laptop uploads are never used for scheduled reports.")
    if BACKGROUND_SCHEDULER_RUNNING:
        st.success("Background scheduler is enabled in this running app process.")
    elif not ENABLE_BACKGROUND_SCHEDULER:
        st.warning("Background execution is disabled. This is recommended on Streamlit Community Cloud because app sleep/restarts cannot guarantee scheduled execution. Use an external scheduler for production runs.")
    else:
        st.error("Background scheduler could not start. Check the execution status below and install requirements.txt dependencies.")

    cfg = load_schedule_config()
    try:
        recipient_lists = load_recipient_lists()
    except Exception as exc:
        recipient_lists = {}
        st.error(f"Could not load saved recipient lists: {exc}")
    if not recipient_lists:
        st.error("No saved recipient lists are configured. Add [recipient_lists] to Streamlit secrets or configure recipient_lists.json locally before enabling scheduled emails.")
    with st.form("scheduler_configuration"):
        enabled = st.checkbox("Enable this schedule", value=bool(cfg.get("enabled", False)))
        date_options = ["yesterday", "latest available day", "custom range"]
        date_mode = st.radio("Report date range", date_options,
                             index=date_options.index(cfg.get("date_mode", "yesterday")) if cfg.get("date_mode", "yesterday") in date_options else 0,
                             horizontal=True)
        default_start = pd.to_datetime(cfg.get("custom_start", "2026-01-01")).date()
        default_end = pd.to_datetime(cfg.get("custom_end", str(default_start))).date()
        if date_mode == "custom range":
            d1, d2 = st.columns(2)
            custom_start = d1.date_input("Custom start date", value=default_start)
            custom_end = d2.date_input("Custom end date", value=default_end)
        else:
            custom_start, custom_end = default_start, default_end
        current_time = dt_time.fromisoformat(cfg.get("run_time", "08:00"))
        run_time = st.time_input("Run time", value=current_time, help=f"Uses {SCHEDULER_TIMEZONE} timezone.")
        frequency_options = ["Once", "Daily", "Repeat N times"]
        frequency = st.selectbox("Run frequency", frequency_options,
                                 index=frequency_options.index(cfg.get("frequency", "Daily")) if cfg.get("frequency", "Daily") in frequency_options else 1)
        repeat_count = st.number_input("Number of daily runs", min_value=1, max_value=365, value=max(1, int(cfg.get("repeat_count", 5))), disabled=frequency != "Repeat N times")
        recipient_names = list(recipient_lists.keys())
        prior_list = cfg.get("recipient_list", recipient_names[0] if recipient_names else "")
        recipient_index = recipient_names.index(prior_list) if prior_list in recipient_names else 0
        recipient_list = st.selectbox("Saved recipient list", recipient_names, index=recipient_index, disabled=not recipient_names)
        use_llm_schedule = st.checkbox("Use Ollama for comment analysis", value=bool(cfg.get("use_llm", False)), help="Leave off for cloud deployment unless a reachable Ollama service is configured.")
        save_clicked = st.form_submit_button("Save schedule", type="primary", disabled=not recipient_names)
        if save_clicked:
            if date_mode == "custom range" and custom_start > custom_end:
                st.error("Custom start date must be on or before end date.")
            else:
                remaining = int(repeat_count) if frequency == "Repeat N times" else int(cfg.get("remaining_runs", 1))
                saved = save_schedule_config({
                    "enabled": enabled, "date_mode": date_mode,
                    "custom_start": str(custom_start), "custom_end": str(custom_end),
                    "run_time": run_time.strftime("%H:%M"), "frequency": frequency,
                    "repeat_count": int(repeat_count), "remaining_runs": remaining,
                    "recipient_list": recipient_list, "use_llm": use_llm_schedule,
                })
                st.success("Schedule saved.")
                if enabled and not ENABLE_BACKGROUND_SCHEDULER:
                    st.info("Configuration is saved, but this process will not execute it automatically while background scheduling is disabled.")
                st.rerun()

    st.divider()
    st.subheader("Execution status")
    status = load_scheduler_status()
    st.write(f"**Status:** {status.get('status', 'Not run yet')}")
    if status.get("started_at"):
        st.caption(f"Started: {status['started_at']}")
    if status.get("finished_at"):
        st.caption(f"Finished: {status['finished_at']}")
    if status.get("last_report_period"):
        st.caption(f"Last report period: {status['last_report_period']}")
    if status.get("recipient_list"):
        st.caption(f"Recipient list: {status['recipient_list']} ({', '.join(status.get('recipients', []))})")
    if status.get("error"):
        st.error(f"Last scheduler issue: {status['error']}")
    if status.get("last_overlap_message"):
        st.warning(f"Overlap protection: {status['last_overlap_message']} (total skipped overlaps: {status.get('overlap_count', 1)}; last at {status.get('last_overlap_at', 'unknown time')}).")
    if st.button("Run scheduled report now", type="secondary", help="Runs the saved configuration once, including its email send."):
        with st.spinner("Reading Google Sheets data, generating the report, and sending email..."):
            ok = run_scheduled_job()
        latest = load_scheduler_status()
        if ok:
            st.success("Scheduled report completed and email sent.")
        else:
            st.error(f"Scheduled report did not complete: {latest.get('error') or latest.get('status', 'Unknown error')}")
        st.rerun()

    st.markdown("**Failure handling:** missing/unavailable Drive file, no rows in the selected date range, missing recipient list, and Gmail errors are recorded here. Concurrent runs are refused and shown as skipped. The report is only marked successful after the email send succeeds.")

elif page == "How to use":
    st.subheader("Quick start")
    st.markdown("""
    1. Install Python 3.11 or newer.
    2. Run `pip install -r requirements.txt`.
    3. Copy `.env.example` to `.env`; set `DRIVE_DOWNLOAD_URL` to your native Google Sheets URL and configure Gmail if needed.
    4. Install Ollama and pull a model, e.g. `ollama pull gemma3:4b`.
    5. Run `streamlit run app.py`.
    6. Choose Google Sheets (live data) or Laptop (manual test upload). The Scheduler always uses the configured Google Sheet only.
    7. Open Scheduler to configure the date range, time, frequency, and saved recipient list.
    """)
    st.subheader("Chat assistant question examples")
    st.markdown("""
    - `Which customers need recovery follow-up?`
    - `Show customer impact by category.`
    - `What alerts and risks need attention?`
    - `Which customers are impacted by Baggage issues?`
    - `Why is Baggage low CSAT?`
    - `Which flights or airports have the most low-CSAT records?`
    - `Give me an executive summary and recommended actions.`
    - `Prepare a report for this date range.`
    """)
    st.subheader("Important")
    st.markdown("""
    - The included Excel file is synthetic demonstration data, not real customer data.
    - Customer impact counts use distinct `CustomerName` values in low-CSAT records; the schema does not include a verified customer ID.
    - Staff CSAT comparisons are descriptive, not proof that a staff member caused a score.
    - Theme/alert rules are evidence signals, not confirmed operational root causes.
    - Chat/report questions do not send email directly. Review a generated report and explicitly confirm delivery.
    - Local Ollama uses a loopback endpoint only. On Streamlit Community Cloud, the app container's localhost is not your laptop's Ollama; Python insights still work online, but real Ollama commentary requires running the admin app where Ollama is installed.
    - On Streamlit Community Cloud, do not rely on an in-process background scheduler: the app may sleep/restart. Use an external scheduler/worker for reliable production delivery.
    - The Scheduler reads the configured native Google Sheet through the service account and never falls back to the local/sample Excel file.
    """)
