"""Scheduled entry point. Always reads the configured native Google Sheets source, never a local desktop/sample file."""
import logging
from datetime import date, timedelta
from config import OLLAMA_MODEL, REPORT_EMAIL_TO, LOGS_DIR, SHEET_NAME
from agent_core import (load_google_sheet, analyze_day, save_report, send_gmail,
                        get_last_processed_date, set_last_processed_date)
from config import DRIVE_DOWNLOAD_URL

LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOGS_DIR / "scheduler.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

def resolve_data():
    """Read the latest configured native Google Sheet; deliberately no local fallback."""
    if not DRIVE_DOWNLOAD_URL:
        raise RuntimeError("Google Sheets source is not configured. Set DRIVE_DOWNLOAD_URL in .env.")
    return load_google_sheet(DRIVE_DOWNLOAD_URL, SHEET_NAME)

def main():
    """Process yesterday only. A successful date is not emailed twice."""
    logging.info("Scheduled run started; source=Google Sheets only.")
    yesterday = date.today() - timedelta(days=1)
    target = str(yesterday)
    try:
        last = get_last_processed_date()
        if last == target:
            logging.info("Yesterday (%s) was already processed successfully; skipping.", target)
            return
        df = resolve_data()
        day_df = df[df["SurveyDate"] == yesterday]
        if day_df.empty:
            logging.info("No survey rows found for yesterday (%s); nothing to email.", target)
            return
        result = analyze_day(df, yesterday, model=OLLAMA_MODEL, use_llm=True)
        save_report(result)
        # Mark processed only after successful email, so failed sends can be retried.
        send_gmail(REPORT_EMAIL_TO, f"Daily Customer Feedback Report — {target}", result["report_markdown"])
        set_last_processed_date(yesterday)
        logging.info("Successfully processed and emailed yesterday (%s).", target)
    except Exception:
        logging.exception("Scheduled run failed for yesterday (%s).", target)
        raise

if __name__ == "__main__":
    main()
