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
from chat_result_html import render_chat_result_html, render_chat_result_plain_text
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
        ["Chat assistant", "AI Solution", "Dashboard", "Data preview", "Settings", "Scheduler"],
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
    st.caption("Load live feedback, choose a date range, ask a business question, review the HTML-formatted answer, and share that result by email when needed.")

    refresh_col, source_col = st.columns([1, 3])
    with refresh_col:
        refresh_chat_data = st.button("Load / refresh feedback rows", type="primary", key="refresh_assistant_data")
    with source_col:
        st.caption(f"Live data source: {drive_url or 'not configured'} · Worksheet: {sheet}")
    if refresh_chat_data:
        try:
            st.session_state["assistant_df"] = load_google_sheet(drive_url, sheet_name=sheet)
            st.session_state["assistant_data_loaded_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state["assistant_messages"] = []
            st.session_state.pop("pending_report", None)
            st.session_state.pop("assistant_ai_interpretation", None)
            st.session_state.pop("assistant_latest_result", None)
            st.success(f"Loaded {len(st.session_state['assistant_df'])} feedback rows from the live Google Sheet.")
        except Exception as exc:
            st.error(f"Could not load live feedback: {exc}")

    assistant_df = st.session_state.get("assistant_df")
    if assistant_df is None:
        st.info("Click **Load / refresh feedback rows** to load the latest submissions before asking questions.")
    else:
        if st.session_state.get("assistant_data_loaded_at"):
            st.caption(f"Data last refreshed: {st.session_state['assistant_data_loaded_at']} · {len(assistant_df)} rows")
        available_dates = get_available_dates(assistant_df)
        if not available_dates:
            st.warning("No valid survey dates are available in the live data.")
        else:
            date_left, date_right = st.columns(2)
            chat_start = date_left.date_input("Start date", value=available_dates[0], min_value=available_dates[0], max_value=available_dates[-1], key="chat_range_start")
            chat_end = date_right.date_input("End date", value=available_dates[-1], min_value=available_dates[0], max_value=available_dates[-1], key="chat_range_end")
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
                    st.caption(f"Model configured: {model} · Ollama interpretation: {'enabled' if use_llm else 'disabled in Settings'}. Questions asking why, explain, or recommend should invoke the local model; if Ollama fails, the answer will say clearly that it is Python-only.")
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

                st.markdown("#### Example questions")
                st.caption("Choose an example to put it in the question box, or type your own question below.")
                examples = [
                    ("Executive summary", "Give me an executive summary and recommended actions."),
                    ("Top low-CSAT category", "Which category has the most low-CSAT records?"),
                    ("Low-score comments", "Show low score comments and identify recurring issues."),
                    ("Why CSAT declined?", "Why did CSAT decline in this period?"),
                ]
                # Give each submitted question a fresh widget key. This prevents Streamlit's
                # form-clear behavior from leaving the next submission bound to a stale blank
                # value after the first question.
                question_generation = int(st.session_state.get("chat_question_generation", 0))
                question_key = f"chat_question_input_{question_generation}"
                example_cols = st.columns(4)
                for col, (label, example_question) in zip(example_cols, examples):
                    with col:
                        if st.button(label, key=f"chat_example_{label.lower().replace(' ', '_').replace('?', '')}", use_container_width=True):
                            st.session_state[question_key] = example_question

                with st.form("feedback_chat_form", clear_on_submit=False):
                    user_question = st.text_input(
                        "Chat assistant question",
                        placeholder="Ask about CSAT, customer complaints, categories, trends, root-cause hypotheses, or actions…",
                        key=question_key,
                    )
                    ask_clicked = st.form_submit_button("Ask assistant", type="primary")
                if ask_clicked:
                    if not user_question.strip():
                        st.warning("Enter a question first.")
                    elif chat_data.empty:
                        st.warning("There are no feedback records in this date range.")
                    else:
                        wants_report, explicitly_asks_send = is_report_request(user_question)
                        if wants_report:
                            st.session_state.pop("assistant_latest_result", None)
                            try:
                                report_result = analyze_day(assistant_df, (chat_start, chat_end), model=model, use_llm=use_llm)
                                st.session_state["pending_report"] = {
                                    "result": report_result,
                                    "start": str(chat_start),
                                    "end": str(chat_end),
                                    "send_requested": explicitly_asks_send,
                                }
                                reply = (f"I prepared a report for **{chat_start} to {chat_end}** using Python analytics. "
                                         "It has **not** been emailed. Review the HTML preview below, choose a saved recipient list, "
                                         "and confirm sending when ready.")
                            except Exception as exc:
                                reply = f"I could not prepare the report: {exc}"
                        else:
                            reply = answer_question(chat_data, user_question, model=model, use_llm=use_llm)
                            st.session_state["assistant_latest_result"] = {
                                "question": user_question,
                                "answer": reply,
                                "start": str(chat_start),
                                "end": str(chat_end),
                            }
                        messages = st.session_state.setdefault("assistant_messages", [])
                        messages.append({"role": "user", "content": user_question})
                        messages.append({"role": "assistant", "content": reply, "question": user_question,
                                         "start": str(chat_start), "end": str(chat_end)})
                        # A new key clears the input for the next question without clearing
                        # a widget's session_state after the widget has been instantiated.
                        st.session_state["chat_question_generation"] = question_generation + 1

                # Render assistant answers in a safe, email-friendly HTML card.
                messages = st.session_state.get("assistant_messages", [])
                for index, message in enumerate(messages):
                    if message.get("role") == "user":
                        with st.chat_message("user"):
                            st.markdown(message.get("content", ""))
                    else:
                        question_text = message.get("question", "")
                        if not question_text and index > 0:
                            question_text = messages[index - 1].get("content", "")
                        result_start = message.get("start", str(chat_start))
                        result_end = message.get("end", str(chat_end))
                        answer_text = str(message.get("content", ""))
                        with st.chat_message("assistant"):
                            components.html(
                                render_chat_result_html(question_text, answer_text, result_start, result_end),
                                height=min(760, max(220, 155 + len(answer_text.splitlines()) * 25)),
                                scrolling=True,
                            )

                # Share only the latest normal Q&A result; prepared full reports use the separate report flow below.
                latest_result = st.session_state.get("assistant_latest_result")
                if latest_result and not st.session_state.get("pending_report"):
                    st.divider()
                    st.subheader("Share this result by email")
                    st.caption(f"Result date range: {latest_result['start']} to {latest_result['end']}. The email contains the formatted HTML result and a plain-text alternative.")
                    recipient_lists = {}
                    recipient_storage_error = None
                    try:
                        recipient_lists = load_recipient_lists()
                    except Exception as exc:
                        recipient_storage_error = str(exc)
                    if recipient_storage_error:
                        st.warning(f"Could not load saved recipient lists: {recipient_storage_error}")
                        st.info("Configure the private recipient-list spreadsheet or check the settings, then retry.")
                    elif not recipient_lists:
                        st.info("No saved recipient lists are available. Create a list on the Settings page before emailing results.")
                    else:
                        list_names = list(recipient_lists.keys())
                        selected_result_list = st.selectbox("Email recipient list", list_names, key="chat_result_recipient_list")
                        result_addresses = recipient_lists.get(selected_result_list, [])
                        st.caption(f"Recipients ({len(result_addresses)}): " + (", ".join(result_addresses) if result_addresses else "This list is empty."))
                        confirm_result_email = st.checkbox("I reviewed this result and confirm emailing it to the selected list.", key="confirm_chat_result_email")
                        if st.button("Email HTML result", type="primary", disabled=(not confirm_result_email or not result_addresses), key="email_chat_result"):
                            try:
                                period = f"{latest_result['start']} to {latest_result['end']}"
                                send_gmail(
                                    ", ".join(result_addresses),
                                    f"CSAT Assistant Result — {period}",
                                    render_chat_result_plain_text(latest_result["question"], latest_result["answer"], latest_result["start"], latest_result["end"]),
                                    html_body=render_chat_result_html(latest_result["question"], latest_result["answer"], latest_result["start"], latest_result["end"]),
                                )
                                st.success(f"HTML result emailed to the '{selected_result_list}' recipient list.")
                                st.session_state.pop("assistant_latest_result", None)
                            except Exception as exc:
                                st.error(f"Email failed: {exc}")

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
                                st.session_state.pop("assistant_latest_result", None)
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

elif page == "AI Solution":
    st.subheader("AI feedback analysis — selected dates")
    st.markdown("""
    Select a date range to display the original survey rows and ask **local Gemma (`gemma3:4b`)** to add six AI interpretation columns, including an airline-specific `AI_Category`. The original `Category` column from the survey is preserved. This is designed as a management demonstration: it shows how AI can turn free-text feedback into structured issue signals and possible actions.

    Results are displayed here and can be downloaded as CSV; the original Google Sheet is not modified.
    """)
    with st.expander("How this demonstrates the value of AI", expanded=False):
        st.markdown("""
        - **AI_Category:** classifies the comment into a consistent airline-service category, such as Flight Changes, Refunds, Baggage, or Check-in & Boarding. It is separate from the original survey `Category` column.
        - **Primary/secondary issue:** groups customer complaints beyond the existing form category.
        - **Sentiment:** indicates the tone expressed in the comment.
        - **Root-cause hypothesis:** suggests what to investigate; it is not a confirmed cause.
        - **Recommended action:** gives management a practical next step to validate.

        Python continues to calculate numerical KPIs. Gemma interprets the written comments. Management should validate suggested causes against operational data before taking action.
        """)
    st.caption("Local execution requirement: run this admin app on your laptop while Ollama is running. A Streamlit Cloud server cannot reach Ollama running on your laptop's localhost.")
    if st.button("Load feedback rows", type="secondary", key="howto_load_feedback"):
        with st.spinner("Loading feedback from the configured source..."):
            loaded_df = read_source()
        if loaded_df is not None:
            st.session_state["howto_feedback_df"] = loaded_df
            st.session_state.pop("howto_ai_df", None)

    source_df = st.session_state.get("howto_feedback_df")
    if source_df is not None and not source_df.empty:
        dates = sorted(pd.to_datetime(source_df["SurveyDate"], errors="coerce").dropna().dt.date.unique().tolist())
        if dates:
            date_col1, date_col2 = st.columns(2)
            start_date = date_col1.date_input("Start date", value=dates[0], min_value=dates[0], max_value=dates[-1], key="howto_start_date")
            end_date = date_col2.date_input("End date", value=dates[-1], min_value=dates[0], max_value=dates[-1], key="howto_end_date")
            if start_date > end_date:
                st.error("Start date must be on or before end date.")
            else:
                date_values = pd.to_datetime(source_df["SurveyDate"], errors="coerce").dt.date
                selected_df = source_df.loc[date_values.between(start_date, end_date)].copy().reset_index(drop=True)
                st.write(f"**{len(selected_df):,} survey rows** from {start_date} through {end_date}.")
                st.dataframe(selected_df, use_container_width=True, hide_index=True)
                model_name = st.text_input("Local Ollama model", value=model or "gemma3:4b", key="howto_gemma_model")
                max_rows = st.number_input("Maximum comments to analyze in this run", min_value=1, max_value=500, value=min(30, max(1, len(selected_df))), key="howto_max_rows")
                st.caption("Gemma analyzes comments in batches of 5 per model request to reduce overhead. Larger batches can be faster but may reduce output reliability on small local models.")
                if st.button("Analyze selected rows with Gemma", type="primary", disabled=selected_df.empty, key="howto_analyze_gemma"):
                    from urllib.parse import urlparse
                    import json
                    import requests
                    from config import OLLAMA_URL
                    host = urlparse((OLLAMA_URL or "http://localhost:11434").strip()).hostname
                    if host not in {"localhost", "127.0.0.1", "::1"}:
                        st.error("Local-only mode is enabled. Set OLLAMA_URL to http://localhost:11434.")
                    else:
                        result_df = selected_df.head(int(max_rows)).copy()
                        airline_categories = [
                            "Booking & Ticketing",
                            "Flight Changes",
                            "Cancellations & Disruptions",
                            "Flight Delays",
                            "Refunds",
                            "Baggage",
                            "Check-in & Boarding",
                            "Fares, Fees & Payments",
                            "Customer Service & Staff Communication",
                            "Airport Experience",
                            "Seat & Cabin Experience",
                            "Onboard Service",
                            "Special Assistance",
                            "Loyalty & Miles",
                            "Website & Mobile App",
                            "Other / Unclear",
                        ]
                        new_columns = ["primary_issue", "secondary_issue", "sentiment", "root_cause_hypothesis", "recommended_action", "AI_Category"]
                        for col in new_columns:
                            if col not in result_df.columns:
                                result_df[col] = ""
                        progress = st.progress(0, text="Preparing comment batches for Gemma...")
                        try:
                            from gemma_batch_analysis import analyze_feedback_batch

                            # Avoid one model generation per row: send small groups in one request.
                            # Stable row_id values map every returned classification to its source row.
                            batch_size = 5
                            pending = []
                            for idx, row in result_df.iterrows():
                                comment = str(row.get("CustomerComment", "") or "").strip()
                                if not comment:
                                    empty_values = {
                                        "primary_issue": "No comment provided",
                                        "secondary_issue": "Not stated",
                                        "sentiment": "Unknown",
                                        "root_cause_hypothesis": "Insufficient text to suggest a cause",
                                        "recommended_action": "Review other survey fields if action is required",
                                        "AI_Category": "Other / Unclear",
                                    }
                                    for col in new_columns:
                                        result_df.at[idx, col] = empty_values.get(col, "")
                                else:
                                    pending.append({
                                        "row_id": int(idx),
                                        "comment": comment[:1200],
                                        "csat_score": str(row.get("CSATScore", "")),
                                        "original_category": str(row.get("Category", "")),
                                    })

                            processed = 0
                            for offset in range(0, len(pending), batch_size):
                                batch = pending[offset:offset + batch_size]
                                returned = analyze_feedback_batch(
                                    batch,
                                    model=model_name.strip() or "gemma3:4b",
                                    ollama_url=OLLAMA_URL,
                                    categories=airline_categories,
                                )
                                expected_ids = {item["row_id"] for item in batch}
                                missing_ids = expected_ids - set(returned)
                                # Repair an incomplete batch response with small single-row retries.
                                for item in batch:
                                    if item["row_id"] in missing_ids:
                                        returned.update(analyze_feedback_batch(
                                            [item],
                                            model=model_name.strip() or "gemma3:4b",
                                            ollama_url=OLLAMA_URL,
                                            categories=airline_categories,
                                        ))
                                missing_ids = expected_ids - set(returned)
                                if missing_ids:
                                    raise ValueError(f"Gemma did not return results for row IDs: {sorted(missing_ids)}. Retry this batch.")

                                for item in batch:
                                    row_id = item["row_id"]
                                    values = returned[row_id]
                                    predicted_category = str(values.get("AI_Category", "") or "").strip()
                                    values["AI_Category"] = predicted_category if predicted_category in airline_categories else "Other / Unclear"
                                    for col in new_columns:
                                        value = values.get(col, "")
                                        result_df.at[row_id, col] = str(value).strip() if value is not None else ""
                                    processed += 1
                                progress.progress(
                                    processed / max(1, len(pending)),
                                    text=f"Gemma analyzed {processed} of {len(pending)} comments in batches of {batch_size}...",
                                )

                            st.session_state["howto_ai_df"] = result_df
                            st.session_state["howto_ai_range"] = (str(start_date), str(end_date))
                            st.session_state.pop("ai_solution_latest_result", None)
                            st.success(f"Gemma analyzed {len(result_df)} row(s) using batches of up to {batch_size}; empty comments were handled locally.")
                        except requests.exceptions.ConnectionError:
                            st.error("Could not connect to Ollama. Start Ollama and verify `ollama run gemma3:4b` works on this laptop.")
                        except Exception as exc:
                            st.error(f"Gemma analysis stopped: {exc}")
                            st.session_state["howto_ai_df"] = result_df
                            st.session_state["howto_ai_range"] = (str(start_date), str(end_date))
                            st.session_state.pop("ai_solution_latest_result", None)
                            st.success(f"Gemma analyzed {len(result_df)} row(s). Review the hypotheses before using them for decisions.")
                        except requests.exceptions.ConnectionError:
                            st.error("Could not connect to Ollama. Start Ollama and verify `ollama run gemma3:4b` works on this laptop.")
                        except Exception as exc:
                            st.error(f"Gemma analysis stopped: {exc}")
                ai_df = st.session_state.get("howto_ai_df")
                ai_range = st.session_state.get("howto_ai_range")
                active_range = (str(start_date), str(end_date))
                if ai_df is not None and ai_range == active_range:
                    st.subheader("Results with AI interpretation columns")
                    st.dataframe(ai_df, use_container_width=True, hide_index=True)
                    csv = ai_df.to_csv(index=False).encode("utf-8-sig")
                    st.download_button("Download analyzed rows as CSV", data=csv, file_name=f"gemma_feedback_{start_date}_to_{end_date}.csv", mime="text/csv", key="howto_download_ai_csv")
                    st.info("Gemma generated AI_Category, primary/secondary issues, sentiment, root-cause hypotheses, and recommended actions. Hypotheses are not verified facts; the original Google Sheet has not been changed.")

                    st.divider()
                    st.subheader("Ask Gemma to analyze this AI-enriched table")
                    st.caption("This assistant uses the exact table above, including its AI_Category and interpretation columns. Ask for patterns, evidence-based explanations, priorities, and management actions. It does not simply summarize KPI counts.")
                    ai_sample_questions = [
                        ("Main drivers", "Analyze this table. What are the strongest drivers of low CSAT? Use AI_Category, primary_issue, sentiment, and original comments as evidence."),
                        ("Why CSAT is low", "Why are customers dissatisfied in this table? Separate observed evidence from root-cause hypotheses, and recommend actions."),
                        ("Compare positive vs low", "Compare positive-CSAT and low-CSAT feedback. What issues differ, and what should management prioritize?"),
                        ("Executive action plan", "Prepare an executive HTML-ready summary of the top three issues, evidence, hypotheses, actions, and how to measure improvement."),
                    ]
                    ai_q_generation = int(st.session_state.get("ai_solution_question_generation", 0))
                    ai_question_key = f"ai_solution_question_{ai_q_generation}"
                    ai_example_cols = st.columns(4)
                    for example_col, (example_label, example_text) in zip(ai_example_cols, ai_sample_questions):
                        with example_col:
                            if st.button(example_label, key=f"ai_solution_example_{example_label.lower().replace(' ', '_')}", use_container_width=True):
                                st.session_state[ai_question_key] = example_text
                    with st.form("ai_solution_analysis_form", clear_on_submit=False):
                        ai_question = st.text_area(
                            "Question about the AI-enriched table",
                            placeholder="Example: Which recurring issues are most associated with low CSAT, and what actions should management take?",
                            key=ai_question_key,
                            height=95,
                        )
                        ai_ask_clicked = st.form_submit_button("Analyze table with Gemma", type="primary")
                    if ai_ask_clicked:
                        if not ai_question.strip():
                            st.warning("Enter a question or select one of the examples first.")
                        else:
                            with st.spinner(f"Gemma is analyzing {len(ai_df)} enriched records. This may take a moment..."):
                                try:
                                    ai_chat_answer = answer_question(
                                        ai_df, ai_question, model=st.session_state.get("howto_gemma_model", model or "gemma3:4b"),
                                        use_llm=True, force_llm=True,
                                    )
                                    st.session_state["ai_solution_latest_result"] = {
                                        "question": ai_question,
                                        "answer": ai_chat_answer,
                                        "start": str(start_date),
                                        "end": str(end_date),
                                        "model": st.session_state.get("howto_gemma_model", model or "gemma3:4b"),
                                    }
                                    st.session_state["ai_solution_question_generation"] = ai_q_generation + 1
                                except Exception as exc:
                                    st.error(f"Gemma could not analyze this table: {exc}")
                    latest_ai_result = st.session_state.get("ai_solution_latest_result")
                    if latest_ai_result and (latest_ai_result.get("start"), latest_ai_result.get("end")) == active_range:
                        st.markdown("#### AI analysis result (HTML preview)")
                        components.html(
                            render_chat_result_html(latest_ai_result["question"], latest_ai_result["answer"], latest_ai_result["start"], latest_ai_result["end"]),
                            height=min(1050, max(320, 190 + len(latest_ai_result["answer"].splitlines()) * 26)),
                            scrolling=True,
                        )
                        st.caption(f"Analysis model: {latest_ai_result.get('model', 'gemma3:4b')} · Date range: {latest_ai_result['start']} to {latest_ai_result['end']}")
                        with st.expander("View the answer as Markdown text", expanded=False):
                            st.markdown(latest_ai_result["answer"])

                        st.divider()
                        st.subheader("Share the AI analysis with management")
                        ai_result_lists = {}
                        ai_result_storage_error = None
                        try:
                            ai_result_lists = load_recipient_lists()
                        except Exception as exc:
                            ai_result_storage_error = str(exc)
                        if ai_result_storage_error:
                            st.warning(f"Could not load saved recipient lists: {ai_result_storage_error}")
                        elif not ai_result_lists:
                            st.info("No saved recipient lists are available. Create a list on Settings first.")
                        else:
                            ai_result_names = list(ai_result_lists.keys())
                            selected_ai_result_list = st.selectbox("Management email recipient list", ai_result_names, key="ai_solution_result_recipient_list")
                            ai_result_addresses = ai_result_lists.get(selected_ai_result_list, [])
                            st.caption(f"Recipients ({len(ai_result_addresses)}): " + (", ".join(ai_result_addresses) if ai_result_addresses else "This list is empty."))
                            ai_result_confirm = st.checkbox("I reviewed this AI analysis and confirm sending it by email.", key="confirm_ai_solution_result_email")
                            if st.button("Email AI analysis as HTML", type="primary", disabled=(not ai_result_confirm or not ai_result_addresses), key="email_ai_solution_result"):
                                try:
                                    period = f"{latest_ai_result['start']} to {latest_ai_result['end']}"
                                    send_gmail(
                                        ", ".join(ai_result_addresses),
                                        f"Gemma CSAT Analysis — {period}",
                                        render_chat_result_plain_text(latest_ai_result["question"], latest_ai_result["answer"], latest_ai_result["start"], latest_ai_result["end"]),
                                        html_body=render_chat_result_html(latest_ai_result["question"], latest_ai_result["answer"], latest_ai_result["start"], latest_ai_result["end"]),
                                    )
                                    st.success(f"HTML analysis emailed to the '{selected_ai_result_list}' recipient list.")
                                except Exception as exc:
                                    st.error(f"Email failed: {exc}")
                elif ai_df is not None and ai_range != active_range:
                    st.info("The saved Gemma table belongs to a different date range. Click **Analyze selected rows with Gemma** to refresh it for the newly selected dates before asking questions.")
        else:
            st.warning("No valid survey dates were found in the loaded data.")
    elif source_df is not None:
        st.info("The configured data source contains no survey rows.")
