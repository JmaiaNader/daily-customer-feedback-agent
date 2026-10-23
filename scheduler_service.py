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

from agent_core import (analyze_day, load_google_sheet, get_available_dates,
                        save_report, send_gmail)
from email_report import render_html_report
from config import (DRIVE_DOWNLOAD_URL, ENABLE_BACKGROUND_SCHEDULER, LOGS_DIR,
                    OLLAMA_MODEL, RECIPIENT_LISTS_FILE, SCHEDULER_CONFIG_FILE,
                    SCHEDULER_STATUS_FILE, SCHEDULER_TIMEZONE, SHEET_NAME,
                    RECIPIENTS_SPREADSHEET_URL)

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
    """Read managed lists from the private Google Sheet first, then legacy config."""
    if RECIPIENTS_SPREADSHEET_URL:
        try:
            from feedback_service import load_recipient_lists_from_sheet
            managed = load_recipient_lists_from_sheet()
            # Once a private store is configured, never fall back to sample/stale
            # emails if its tab has not yet been created. The UI can initialize it.
            return managed if managed is not None else {}
        except Exception:
            _LOG.exception("Could not load managed recipient lists from the private spreadsheet")
            # Do not silently use stale recipient addresses when the configured source fails.
            raise
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


def save_recipient_lists(lists):
    """Persist the entire named-list mapping to the configured store."""
    normalised = {str(name).strip(): _normalise_emails(emails)
                  for name, emails in (lists or {}).items() if str(name).strip()}
    if RECIPIENTS_SPREADSHEET_URL:
        from feedback_service import save_recipient_lists_to_sheet
        return save_recipient_lists_to_sheet(normalised)
    _write_json(RECIPIENT_LISTS_FILE, normalised)
    return normalised


def _validate_recipient_list(name, emails):
    list_name = str(name or "").strip()
    if not list_name:
        raise ValueError("Enter a name for the recipient list.")
    if len(list_name) > 80:
        raise ValueError("Recipient-list name must be 80 characters or fewer.")
    if isinstance(emails, str):
        raw = emails.replace(";", ",").replace("\n", ",").split(",")
    else:
        raw = list(emails or [])
    normalized = _normalise_emails(raw)
    if not normalized:
        raise ValueError("Add at least one valid email address to the list.")
    invalid = [str(item).strip() for item in raw
               if str(item).strip() and ("@" not in str(item).strip() or any(c.isspace() for c in str(item).strip()))]
    if invalid:
        raise ValueError("Invalid email address(es): " + ", ".join(invalid))
    return list_name, normalized


def _normalise_emails(values):
    if isinstance(values, str):
        values = values.replace(";", ",").replace("\n", ",").split(",")
    result = []
    seen = set()
    for value in values or []:
        address = str(value).strip()
        if not address or "@" not in address or any(char.isspace() for char in address):
            continue
        key = address.casefold()
        if key not in seen:
            result.append(address)
            seen.add(key)
    return result


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
        raise ValueError("The Google Sheet contains no valid SurveyDate values.")
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
        # The scheduler always reads the same native Google Sheet as the dashboard.
        if not DRIVE_DOWNLOAD_URL:
            raise RuntimeError("Google Sheets source is not configured. Set DRIVE_DOWNLOAD_URL in secrets or .env.")
        df = load_google_sheet(DRIVE_DOWNLOAD_URL, SHEET_NAME)
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
                   result["report_markdown"], html_body=render_html_report(result["payload"]))
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
