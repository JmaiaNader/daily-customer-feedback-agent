from pathlib import Path
import pandas as pd
import streamlit as st
from agent_core import (
    load_excel, analyze_day, get_available_dates, send_gmail,
    save_report, get_last_processed_date, set_last_processed_date,
    required_columns
)
from config import BASE_DIR, DATA_FILE, REPORTS_DIR, DRIVE_DOWNLOAD_URL, ENABLE_BACKGROUND_SCHEDULER, SCHEDULER_TIMEZONE
from scheduler_service import (load_schedule_config, save_schedule_config, load_scheduler_status,
                               load_recipient_lists, run_scheduled_job, start_background_scheduler)
from datetime import time as dt_time
from agent_core import download_google_drive_excel

st.set_page_config(page_title="Daily Customer Feedback Agent", page_icon="📊", layout="wide")
st.title("📊 Daily Customer Feedback Analysis Agent")
st.caption("Excel → Python analytics → optional Ollama → Gmail, with configurable report scheduling")
BACKGROUND_SCHEDULER_RUNNING = start_background_scheduler()

with st.sidebar:
    st.header("Settings")
    source = st.radio(
        "Data source",
        ["Google Drive (default file)", "Laptop (test upload)"],
        index=0,
        help="Google Drive is the default source. Laptop upload is intended for manual testing only."
    )
    drive_url = st.text_input(
        "Google Drive Excel URL",
        value=DRIVE_DOWNLOAD_URL,
        help="Use a link that permits downloading. Private company files require Google Drive OAuth/API."
    )
    sheet = st.text_input("Worksheet", value="rowdata")
    model = st.text_input("Ollama model", value="gemma3:4b")
    use_llm = st.toggle("Use local Ollama for comment analysis", value=True)
    st.divider()
    st.caption("For Gmail, configure values in .env. Never put your normal Gmail password in the app.")

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
        st.error("Configure DRIVE_DOWNLOAD_URL in .env or enter a Google Drive URL in the sidebar.")
        return None
    try:
        temp = download_google_drive_excel(drive_url)
        return load_excel(temp, sheet_name=sheet)
    except Exception as e:
        st.error(f"Could not download/read Google Drive file: {e}")
        st.info("This link-based method works only when the file can be downloaded via its link. Private Drive files need OAuth/API access.")
        return None

tab1, tab2, tab3, tab4 = st.tabs(["Run analysis", "Data preview", "Scheduler", "How to use"])

with tab1:
    st.subheader("Run an analysis")
    uploaded_file = None
    if source == "Laptop (test upload)":
        uploaded_file = st.file_uploader("Choose an Excel file from your laptop", type=["xlsx", "xls"], key="desktop_excel_upload")
        st.caption("Desktop uploads are for manual testing and do not change the Scheduler's Google Drive source.")
    else:
        st.caption("The app will load the configured default Excel file from Google Drive.")
    if st.button("Load Excel", type="secondary"):
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
                st.caption("Choose a date range for manual analysis. The Scheduler tab has its own date-range setting.")
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
                    m = result["metrics"]
                    c1,c2,c3,c4 = st.columns(4)
                    c1.metric("Surveys", m["survey_count"])
                    c2.metric("Average CSAT", f'{m["average_csat"]:.2f}/5')
                    c3.metric("CSAT 4–5", f'{m["positive_rate_pct"]:.1f}%')
                    c4.metric("CSAT 1–2", f'{m["low_rate_pct"]:.1f}%')
                    st.subheader(f"Report: {result['payload'].get('report_period', result['payload']['report_date'])}")
                    st.markdown(result["report_markdown"])
                    safe_period = result["payload"]["report_date"]
                    st.download_button("Download report (.md)", result["report_markdown"], file_name=f"customer_feedback_{safe_period}.md")
                    st.download_button("Download structured JSON", result["json_text"], file_name=f"customer_feedback_{safe_period}.json", mime="application/json")
                    if st.button("Save report locally"):
                        path = save_report(result, REPORTS_DIR)
                        st.success(f"Saved: {path}")
                    st.divider()
                    st.subheader("Review before sending")
                    st.caption("The report above is the exact content that will be sent. Review it before confirming. Desktop-loaded data is for testing; the Scheduler always reads Google Drive.")
                    recipient = st.text_input("Send report to", placeholder="you@gmail.com", key="recipient")
                    confirm_send = st.checkbox("I reviewed the report and want to send it by Gmail.")
                    if st.button("Send reviewed report with Gmail", disabled=not confirm_send):
                        try:
                            send_gmail(recipient, f"Customer Feedback Report — {result['payload'].get('report_period', result['payload']['report_date'])}", result["report_markdown"])
                            st.success("Email sent.")
                        except Exception as e:
                            st.error(f"Email failed: {e}")
                    st.warning("Staff ranking uses only the selected date range. Small sample sizes can make rankings unstable.")
    else:
        st.info("Choose Google Drive for the default data source, or Laptop for a manual test upload, then click **Load Excel**.")

with tab2:
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
        st.info("Load the Excel file in the Run analysis tab first.")

with tab4:
    st.subheader("Scheduled report configuration")
    st.caption(f"Schedule timezone: {SCHEDULER_TIMEZONE}. The scheduler always reads Google Drive; laptop uploads are never used for scheduled reports.")
    if BACKGROUND_SCHEDULER_RUNNING:
        st.success("Background scheduler is enabled in this running app process.")
    elif not ENABLE_BACKGROUND_SCHEDULER:
        st.warning("Background execution is disabled. This is recommended on Streamlit Community Cloud because app sleep/restarts cannot guarantee scheduled execution. Use an external scheduler for production runs.")
    else:
        st.error("Background scheduler could not start. Check the execution status below and install requirements.txt dependencies.")

    cfg = load_schedule_config()
    recipient_lists = load_recipient_lists()
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
        with st.spinner("Downloading Google Drive data, generating the report, and sending email..."):
            ok = run_scheduled_job()
        latest = load_scheduler_status()
        if ok:
            st.success("Scheduled report completed and email sent.")
        else:
            st.error(f"Scheduled report did not complete: {latest.get('error') or latest.get('status', 'Unknown error')}")
        st.rerun()

    st.markdown("**Failure handling:** missing/unavailable Drive file, no rows in the selected date range, missing recipient list, and Gmail errors are recorded here. Concurrent runs are refused and shown as skipped. The report is only marked successful after the email send succeeds.")

with tab3:
    st.subheader("Quick start")
    st.markdown("""
1. Install Python 3.11 or newer.
2. Run `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`; set `DRIVE_DOWNLOAD_URL` to your default Google Drive Excel link and configure Gmail if needed.
4. Install Ollama and pull a model, e.g. `ollama pull gemma3:4b`.
5. Run `streamlit run app.py`.
6. Choose Google Drive (default) or Laptop (manual test upload). The Scheduler always uses Google Drive only.
7. Open Scheduler to configure the date range, time, frequency, and saved recipient list.
""")
    st.subheader("Important")
    st.markdown("""
- The included Excel file is synthetic demonstration data, not real customer data.
- Staff CSAT comparisons are descriptive, not proof that a staff member caused a score.
- Manual email requires confirmation. Scheduled email uses the separate Scheduler page and sends automatically when its enabled job runs.
- On Streamlit Community Cloud, do not rely on an in-process background scheduler: the app may sleep/restart. Use an external scheduler/worker for reliable production delivery.
- The Scheduler uses Google Drive only and never falls back to the local/sample Excel. Link-based download requires a link that permits downloading; private company Drive files need OAuth/API authentication.
""")
