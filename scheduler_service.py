"""Small local scheduler layer; the existing analysis and Gmail functions stay unchanged."""
import json
import logging
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
except ImportError:  # Keep unit tests/imports usable before dependencies are installed.
    BackgroundScheduler = CronTrigger = DateTrigger = None

from agent_core import (analyze_day, download_google_drive_excel, get_available_dates,
                        load_excel, save_report, send_gmail)
from config import (DRIVE_DOWNLOAD_URL, ENABLE_BACKGROUND_SCHEDULER, LOGS_DIR,
                    OLLAMA_MODEL, RECIPIENT_LISTS_FILE, SCHEDULER_CONFIG_FILE,
                    SCHEDULER_STATUS_FILE, SCHEDULER_TIMEZONE, SHEET_NAME)

_LOG = logging.getLogger(__name__)
_RUN_LOCK = threading.Lock()
_SCHEDULER = None
_JOB_ID = "customer_feedback_report_job"

DEFAULT_CONFIG = {
    "enabled": False,
    "date_mode": "yesterday",
    "custom_start": str(date.today() - timedelta(days=1)),
    "custom_end": str(date.today() - timedelta(days=1)),
    "run_time": "08:00",
    "frequency": "Daily",
    "repeat_count": 5,
    "remaining_runs": 5,
    "recipient_list": "Default",
    "use_llm": False,
}


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_schedule_config():
    if not SCHEDULER_CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()
    try:
        data = json.loads(SCHEDULER_CONFIG_FILE.read_text(encoding="utf-8"))
        config = DEFAULT_CONFIG.copy()
        config.update(data)
        return config
    except Exception as exc:
        _LOG.exception("Could not read scheduler configuration")
        return {**DEFAULT_CONFIG, "last_config_error": str(exc)}


def save_schedule_config(config):
    clean = DEFAULT_CONFIG.copy()
    clean.update(config)
    clean["updated_at"] = datetime.now(ZoneInfo(SCHEDULER_TIMEZONE)).isoformat(timespec="seconds")
    _write_json(SCHEDULER_CONFIG_FILE, clean)
    refresh_background_job()
    return clean


def load_recipient_lists():
    """Read named lists from Streamlit secrets, then local JSON, then legacy default email."""
    try:
        import streamlit as st
        raw = st.secrets.get("recipient_lists", None)
        if raw:
            result = {str(name): _normalise_emails(values) for name, values in raw.items()}
            return {k: v for k, v in result.items() if v}
    except Exception:
        pass
    if RECIPIENT_LISTS_FILE.exists():
        try:
            raw = json.loads(RECIPIENT_LISTS_FILE.read_text(encoding="utf-8"))
            result = {str(name): _normalise_emails(values) for name, values in raw.items()}
            result = {k: v for k, v in result.items() if v}
            if result:
                return result
        except Exception:
            _LOG.exception("Could not load recipient lists")
    try:
        from config import REPORT_EMAIL_TO
        fallback = _normalise_emails(REPORT_EMAIL_TO)
        return {"Default": fallback} if fallback else {}
    except Exception:
        return {}


def _normalise_emails(values):
    if isinstance(values, str):
        values = values.replace(";", ",").split(",")
    return list(dict.fromkeys(str(v).strip() for v in (values or []) if "@" in str(v)))


def _status_update(**updates):
    try:
        status = {}
        if SCHEDULER_STATUS_FILE.exists():
            status = json.loads(SCHEDULER_STATUS_FILE.read_text(encoding="utf-8"))
        status.update(updates)
        status["updated_at"] = datetime.now(ZoneInfo(SCHEDULER_TIMEZONE)).isoformat(timespec="seconds")
        _write_json(SCHEDULER_STATUS_FILE, status)
    except Exception:
        _LOG.exception("Could not persist scheduler status")


def load_scheduler_status():
    try:
        return json.loads(SCHEDULER_STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "Not run yet"}


def _resolve_dates(config, df):
    available = get_available_dates(df)
    if not available:
        raise ValueError("The Google Drive workbook contains no valid SurveyDate values.")
    mode = config.get("date_mode", "yesterday")
    today = datetime.now(ZoneInfo(SCHEDULER_TIMEZONE)).date()
    if mode == "yesterday":
        target = today - timedelta(days=1)
        return target, target
    if mode == "latest available day":
        target = available[-1]
        return target, target
    if mode == "custom range":
        start = date.fromisoformat(config["custom_start"])
        end = date.fromisoformat(config["custom_end"])
        if start > end:
            raise ValueError("Custom start date must be on or before the end date.")
        return start, end
    raise ValueError(f"Unknown date range option: {mode}")


def run_scheduled_job(config_override=None):
    """Run once, refusing concurrent execution and exposing a persisted outcome."""
    if not _RUN_LOCK.acquire(blocking=False):
        prior = load_scheduler_status()
        _status_update(last_overlap_at=datetime.now(ZoneInfo(SCHEDULER_TIMEZONE)).isoformat(timespec="seconds"),
                       last_overlap_message="A new run was skipped because the previous execution is still running.",
                       overlap_count=int(prior.get("overlap_count", 0)) + 1)
        _LOG.warning("Overlapping scheduled run skipped")
        return False
    started = datetime.now(ZoneInfo(SCHEDULER_TIMEZONE)).isoformat(timespec="seconds")
    _status_update(status="Running", started_at=started, error="", last_report_period="")
    try:
        config = config_override or load_schedule_config()
        # The scheduler intentionally always uses the configured remote Drive source.
        if not DRIVE_DOWNLOAD_URL:
            raise RuntimeError("Google Drive source is not configured. Set DRIVE_DOWNLOAD_URL in secrets or .env.")
        path = download_google_drive_excel(DRIVE_DOWNLOAD_URL)
        df = load_excel(path, SHEET_NAME)
        start, end = _resolve_dates(config, df)
        subset = df[(df["SurveyDate"] >= start) & (df["SurveyDate"] <= end)]
        if subset.empty:
            raise ValueError(f"No survey rows found for selected range {start} to {end}; no email was sent.")
        result = analyze_day(df, (start, end), model=OLLAMA_MODEL, use_llm=bool(config.get("use_llm", False)))
        save_report(result)
        lists = load_recipient_lists()
        list_name = config.get("recipient_list", "Default")
        recipients = lists.get(list_name, [])
        if not recipients:
            raise RuntimeError(f"Recipient list '{list_name}' is missing or empty. No email was sent.")
        send_gmail(", ".join(recipients),
                   f"Customer Feedback Report — {result['payload'].get('report_period', result['payload']['report_date'])}",
                   result["report_markdown"])
        finished = datetime.now(ZoneInfo(SCHEDULER_TIMEZONE)).isoformat(timespec="seconds")
        _status_update(status="Success", started_at=started, finished_at=finished,
                       last_report_period=result["payload"].get("report_period", result["payload"]["report_date"]),
                       recipient_list=list_name, recipients=recipients, error="")
        _LOG.info("Scheduled report emailed for %s to list %s", result["payload"]["report_date"], list_name)
        return True
    except Exception as exc:
        _LOG.exception("Scheduled report job failed")
        _status_update(status="Failed", started_at=started,
                       finished_at=datetime.now(ZoneInfo(SCHEDULER_TIMEZONE)).isoformat(timespec="seconds"),
                       error=str(exc))
        return False
    finally:
        _RUN_LOCK.release()
        _finish_limited_schedule()


def _finish_limited_schedule():
    config = load_schedule_config()
    if not config.get("enabled"):
        return
    frequency = config.get("frequency", "Daily")
    if frequency == "Once":
        config["enabled"] = False
        save_schedule_config(config)
    elif frequency == "Repeat N times":
        remaining = max(0, int(config.get("remaining_runs", config.get("repeat_count", 1))) - 1)
        config["remaining_runs"] = remaining
        if remaining == 0:
            config["enabled"] = False
        # Avoid recursion by writing config directly, then refreshing once.
        _write_json(SCHEDULER_CONFIG_FILE, config)
        refresh_background_job()


def refresh_background_job():
    if BackgroundScheduler is None or _SCHEDULER is None or not _SCHEDULER.running:
        return
    try:
        _SCHEDULER.remove_job(_JOB_ID)
    except Exception:
        pass
    config = load_schedule_config()
    if not ENABLE_BACKGROUND_SCHEDULER or not config.get("enabled"):
        return
    hh, mm = map(int, config.get("run_time", "08:00").split(":"))
    tz = ZoneInfo(SCHEDULER_TIMEZONE)
    if config.get("frequency") == "Once":
        run_day = datetime.now(tz).date()
        run_dt = datetime.combine(run_day, time(hh, mm), tzinfo=tz)
        if run_dt <= datetime.now(tz):
            run_dt += timedelta(days=1)
        trigger = DateTrigger(run_date=run_dt, timezone=tz)
    else:
        trigger = CronTrigger(hour=hh, minute=mm, timezone=tz)
    _SCHEDULER.add_job(run_scheduled_job, trigger=trigger, id=_JOB_ID,
                       replace_existing=True, max_instances=5, coalesce=True,
                       misfire_grace_time=3600)


def start_background_scheduler():
    global _SCHEDULER
    if not ENABLE_BACKGROUND_SCHEDULER:
        return False
    if BackgroundScheduler is None:
        _status_update(status="Scheduler unavailable", error="APScheduler is not installed. Run pip install -r requirements.txt.")
        return False
    if _SCHEDULER is None:
        _SCHEDULER = BackgroundScheduler(timezone=ZoneInfo(SCHEDULER_TIMEZONE))
        _SCHEDULER.start()
    refresh_background_job()
    return True
