import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

def _secret_or_env(key, default=""):
    """Prefer environment variables, then Streamlit secrets, then the default."""
    value = os.getenv(key)
    if value not in (None, ""):
        return value
    try:
        import streamlit as st
        value = st.secrets.get(key, default)
        return default if value is None else value
    except Exception:
        return default

DATA_FILE = Path(_secret_or_env("DATA_FILE", str(BASE_DIR / "data" / "sample_surveys.xlsx")))
REPORTS_DIR = Path(_secret_or_env("REPORTS_DIR", str(BASE_DIR / "reports")))
LOGS_DIR = Path(_secret_or_env("LOGS_DIR", str(BASE_DIR / "logs")))
OLLAMA_URL = _secret_or_env("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = _secret_or_env("OLLAMA_MODEL", "gemma3:4b")
GMAIL_ADDRESS = _secret_or_env("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = _secret_or_env("GMAIL_APP_PASSWORD", "")
REPORT_EMAIL_TO = _secret_or_env("REPORT_EMAIL_TO", "")
DRIVE_DOWNLOAD_URL = _secret_or_env("DRIVE_DOWNLOAD_URL", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = _secret_or_env("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SERVICE_ACCOUNT_FILE = _secret_or_env("GOOGLE_SERVICE_ACCOUNT_FILE", "")
SCHEDULER_TIMEZONE = _secret_or_env("SCHEDULER_TIMEZONE", "Asia/Qatar")
ENABLE_BACKGROUND_SCHEDULER = str(_secret_or_env("ENABLE_BACKGROUND_SCHEDULER", "true")).lower() in {"1", "true", "yes"}
DRIVE_CACHE_FILE = BASE_DIR / "data" / "drive_download.xlsx"
SHEET_NAME = _secret_or_env("SHEET_NAME", "rowdata")
SCHEDULER_CONFIG_FILE = Path(_secret_or_env("SCHEDULER_CONFIG_FILE", str(BASE_DIR / "scheduler_config.json")))
SCHEDULER_STATUS_FILE = Path(_secret_or_env("SCHEDULER_STATUS_FILE", str(LOGS_DIR / "scheduler_status.json")))
RECIPIENT_LISTS_FILE = Path(_secret_or_env("RECIPIENT_LISTS_FILE", str(BASE_DIR / "recipient_lists.json")))
# For a hosted app, use a separate PRIVATE spreadsheet for recipient addresses.
# Do not store email recipients in the feedback spreadsheet if it is publicly viewable.
RECIPIENTS_SPREADSHEET_URL = _secret_or_env("RECIPIENTS_SPREADSHEET_URL", "").strip()
RECIPIENTS_SHEET_NAME = _secret_or_env("RECIPIENTS_SHEET_NAME", "recipient_lists").strip() or "recipient_lists"
