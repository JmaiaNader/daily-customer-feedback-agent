"""Backend services for workshop feedback submissions.

This module deliberately does not call Ollama. Saving feedback must work even
when the local model is stopped; local-model analysis remains the reporting layer.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import json
import re
import uuid

import pandas as pd

from config import (
    DATA_FILE,
    DRIVE_DOWNLOAD_URL,
    GOOGLE_SERVICE_ACCOUNT_JSON,
    GOOGLE_SERVICE_ACCOUNT_FILE,
    BASE_DIR,
    SCHEDULER_TIMEZONE,
    SHEET_NAME, RECIPIENTS_SPREADSHEET_URL, RECIPIENTS_SHEET_NAME,
)

STAFF_LIST = [
    {"StaffID": "S1001", "StaffName": "Amira Ben Salem"},
    {"StaffID": "S1002", "StaffName": "Youssef Trabelsi"},
    {"StaffID": "S1003", "StaffName": "Sami Haddad"},
]

REQUIRED_SHEET_HEADERS = {
    "SurveyID", "SurveyDate", "StaffID", "StaffName", "Category",
    "CustomerComment", "CSATScore",
}
AUTO_ADDED_HEADERS = ("CustomerName", "FlightNumber", "Airport")
# These flight/airport pairs come from the synthetic historical workshop data.
# New workshop records cycle through these pairs; they are demo assignments, not
# evidence that a real customer travelled on that flight.
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
_SHEETS_LOCK = RLock()


def validate_submission(customer_name, feedback, score):
    """Normalize the three participant inputs or raise ValueError."""
    name = "" if customer_name is None else str(customer_name).strip()
    comment = "" if feedback is None else str(feedback).strip()

    if not name:
        raise ValueError("Please enter your name.")
    if len(name) > 100:
        raise ValueError("Name must be 100 characters or fewer.")
    if not comment:
        raise ValueError("Please enter your feedback.")
    if len(comment) < 3:
        raise ValueError("Feedback must contain at least 3 characters.")
    if len(comment) > 5000:
        raise ValueError("Feedback must be 5000 characters or fewer.")
    if isinstance(score, bool):
        raise ValueError("CSAT score must be a whole number from 1 to 5.")
    try:
        numeric_score = int(score)
        if str(score).strip() not in {str(numeric_score), f"{numeric_score}.0"}:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("CSAT score must be a whole number from 1 to 5.") from None
    if numeric_score < 1 or numeric_score > 5:
        raise ValueError("CSAT score must be between 1 and 5.")

    return {"CustomerName": name, "CustomerComment": comment, "CSATScore": numeric_score}


def classify_feedback(feedback):
    """Simple transparent category rules using categories already in the sample data."""
    text = (feedback or "").casefold()
    rules = [
        ("Baggage", ("baggage", "luggage", "suitcase", "bag arrived", "lost bag", "damaged bag")),
        ("Check-in", ("check in", "check-in", "checkin", "counter", "queue", "kiosk", "boarding pass")),
        ("Boarding", ("boarding", "gate", "overhead bin", "priority boarding")),
        ("Cabin Crew", ("cabin crew", "flight attendant", "attendant", "onboard service")),
        ("Airport Assistance", ("wheelchair", "mobility assistance", "special assistance", "airport assistance")),
    ]
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    return "Customer Service"


def next_staff(last_staff_id, staff_list=None):
    """Choose the next staff member in a round-robin sequence."""
    staff = list(staff_list or STAFF_LIST)
    if not staff:
        raise ValueError("The workshop staff list is empty.")
    ids = [str(item["StaffID"]) for item in staff]
    last = str(last_staff_id).strip() if last_staff_id is not None else ""
    if last in ids:
        return staff[(ids.index(last) + 1) % len(staff)].copy()
    return staff[0].copy()


def build_submission_record(customer_name, feedback, score, staff=None, now=None,
                            flight_number="AB101", airport="DOH"):
    """Create the complete backend-owned row after validating participant inputs."""
    validated = validate_submission(customer_name, feedback, score)
    assigned_staff = (staff or STAFF_LIST[0]).copy()
    local_now = now or datetime.now(ZoneInfo(SCHEDULER_TIMEZONE))
    survey_id = f"FB-{local_now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
    return {
        "SurveyID": survey_id,
        # Store a date only; analysis already normalizes SurveyDate to a date.
        "SurveyDate": local_now.date().isoformat(),
        "StaffID": assigned_staff["StaffID"],
        "StaffName": assigned_staff["StaffName"],
        "Category": classify_feedback(validated["CustomerComment"]),
        "CustomerName": validated["CustomerName"],
        "CustomerComment": validated["CustomerComment"],
        "CSATScore": validated["CSATScore"],
        # Workshop flight and airport values are assigned by the backend.
        # submit_feedback passes a rotating pair taken from existing demo data.
        "FlightNumber": str(flight_number or "AB101"),
        "Airport": str(airport or "DOH"),
        "Channel": "Workshop Feedback Form",
        "Language": "",
    }


def spreadsheet_id_from_url(url=None):
    """Extract the spreadsheet ID from the configured Google Sheets URL."""
    parsed = urlparse((url if url is not None else DRIVE_DOWNLOAD_URL).strip())
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", parsed.path)
    if not match:
        raise RuntimeError("DRIVE_DOWNLOAD_URL must be a Google Sheets spreadsheet URL.")
    return match.group(1)


def _quoted_sheet_name(name=None):
    sheet = (name or SHEET_NAME).replace("'", "''")
    return f"'{sheet}'"


def _load_service_account_info():
    """Load service-account credentials from a protected JSON file or JSON secret.

    Prefer GOOGLE_SERVICE_ACCOUNT_FILE for local development so the private key
    stays in a file ignored by Git. GOOGLE_SERVICE_ACCOUNT_JSON is retained for
    hosted deployments that store the JSON text in a secret.
    """
    if GOOGLE_SERVICE_ACCOUNT_FILE:
        credential_path = Path(GOOGLE_SERVICE_ACCOUNT_FILE).expanduser()
        if not credential_path.is_absolute():
            credential_path = BASE_DIR / credential_path
        if not credential_path.is_file():
            raise RuntimeError(
                f"Service-account JSON file was not found: {credential_path}. "
                "Check GOOGLE_SERVICE_ACCOUNT_FILE in your .env file."
            )
        try:
            return json.loads(credential_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read service-account JSON file: {exc}") from exc

    if GOOGLE_SERVICE_ACCOUNT_JSON:
        try:
            return json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_JSON must contain the complete JSON key content."
            ) from exc

    raise RuntimeError(
        "Google Sheets writing is not configured. Set GOOGLE_SERVICE_ACCOUNT_FILE "
        "to your private JSON key file path in .env, or configure "
        "GOOGLE_SERVICE_ACCOUNT_JSON in Streamlit Secrets. Enable the Google Sheets API "
        "and share the spreadsheet with the service account email as an Editor."
    )


def _sheets_service():
    """Build a Google Sheets API client with write scope from the configured service account."""
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        info = _load_service_account_info()
        credentials = Credentials.from_service_account_info(info, scopes=[SHEETS_SCOPE])
        return build("sheets", "v4", credentials=credentials, cache_discovery=False)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not initialize Google Sheets access: {exc}") from exc


def _read_sheet_values(service, spreadsheet_id, sheet_name=None):
    range_name = f"{_quoted_sheet_name(sheet_name)}!A:Z"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_name
    ).execute()
    return result.get("values", [])



def _spreadsheet_tab_titles(service, spreadsheet_id):
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties.title"
    ).execute()
    return [
        str(item.get("properties", {}).get("title", ""))
        for item in metadata.get("sheets", [])
    ]


def load_recipient_lists_from_sheet(*, service=None, spreadsheet_url=None, sheet_name=None):
    """Load persistent recipient lists from a separate private Google spreadsheet.

    Returns None if no separate recipient spreadsheet is configured or its recipient
    tab has not yet been created. An existing tab with only a header returns {} so an
    intentionally emptied store is not replaced by stale legacy settings.
    """
    url = (spreadsheet_url if spreadsheet_url is not None else RECIPIENTS_SPREADSHEET_URL).strip()
    if not url:
        return None
    api = service or _sheets_service()
    spreadsheet_id = spreadsheet_id_from_url(url)
    tab = sheet_name or RECIPIENTS_SHEET_NAME or "recipient_lists"
    if tab not in _spreadsheet_tab_titles(api, spreadsheet_id):
        return None
    safe_tab = tab.replace("'", "''")
    result = api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"'{safe_tab}'!A:B",
        valueRenderOption="FORMATTED_VALUE",
    ).execute()
    values = result.get("values", [])
    if not values:
        return {}
    headers = [str(v).strip().casefold() for v in values[0]]
    if headers[:2] != ["listname", "email"]:
        raise RuntimeError(
            f"The '{tab}' tab must have these columns in row 1: ListName, Email. "
            "Do not use the public feedback spreadsheet for recipients."
        )
    lists = {}
    for row in values[1:]:
        name = str(row[0]).strip() if row else ""
        email = str(row[1]).strip() if len(row) > 1 else ""
        if not name:
            continue
        lists.setdefault(name, [])
        if email and "@" in email and not any(c.isspace() for c in email):
            if email.casefold() not in {existing.casefold() for existing in lists[name]}:
                lists[name].append(email)
    return lists


def save_recipient_lists_to_sheet(lists, *, service=None, spreadsheet_url=None, sheet_name=None):
    """Replace all saved recipient lists in a dedicated private Google spreadsheet."""
    url = (spreadsheet_url if spreadsheet_url is not None else RECIPIENTS_SPREADSHEET_URL).strip()
    if not url:
        raise RuntimeError(
            "Recipient-list storage is not configured. Create a separate PRIVATE Google spreadsheet, "
            "share it with the service account as Editor, and set RECIPIENTS_SPREADSHEET_URL."
        )
    api = service or _sheets_service()
    spreadsheet_id = spreadsheet_id_from_url(url)
    tab = sheet_name or RECIPIENTS_SHEET_NAME or "recipient_lists"
    if tab not in _spreadsheet_tab_titles(api, spreadsheet_id):
        try:
            api.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": tab}}}],},
            ).execute()
        except Exception:
            # A concurrent first save may already have created the tab.
            if tab not in _spreadsheet_tab_titles(api, spreadsheet_id):
                raise
    safe_tab = tab.replace("'", "''")
    api.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=f"'{safe_tab}'!A:Z", body={}
    ).execute()
    rows = [["ListName", "Email"]]
    for name in sorted(lists, key=lambda item: str(item).casefold()):
        list_name = str(name).strip()
        if not list_name:
            continue
        raw_emails = lists[name]
        if isinstance(raw_emails, str):
            raw_emails = re.split(r"[,;\n]+", raw_emails)
        emails = []
        seen = set()
        for item in raw_emails or []:
            address = str(item).strip()
            if address and "@" in address and not any(c.isspace() for c in address):
                if address.casefold() not in seen:
                    emails.append(address)
                    seen.add(address.casefold())
        if emails:
            rows.extend([[list_name, address] for address in emails])
        else:
            # Preserve an intentionally created but empty list.
            rows.append([list_name, ""])
    api.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"'{safe_tab}'!A1",
        valueInputOption="RAW", body={"values": rows},
    ).execute()
    return {name: list(emails) for name, emails in lists.items()}

def _column_letter(number):
    """Convert a one-based column number to an A1 column label."""
    if number < 1:
        raise ValueError("Column number must be positive.")
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _add_header_if_missing(service, spreadsheet_id, headers, header, sheet_name=None):
    """Add a missing column at the end, preserving all existing column positions."""
    if header in headers:
        return headers
    column = _column_letter(len(headers) + 1)
    range_name = f"{_quoted_sheet_name(sheet_name)}!{column}1"
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="RAW",
        body={"values": [[header]]},
    ).execute()
    return headers + [header]


def _add_customer_name_header(service, spreadsheet_id, headers, sheet_name=None):
    """Backward-compatible helper used by the one-time customer-name migration."""
    return _add_header_if_missing(service, spreadsheet_id, headers, "CustomerName", sheet_name)


def _sheet_data_rows(rows):
    """Accept either raw values (including the header row) or data rows only."""
    if rows and any(str(value).strip() == "SurveyID" for value in rows[0]):
        return rows[1:]
    return rows


def _flight_pairs(headers, rows):
    """Return distinct (FlightNumber, Airport) pairs from historical workshop rows."""
    if "FlightNumber" not in headers or "Airport" not in headers:
        return []
    rows = _sheet_data_rows(rows)
    flight_idx, airport_idx = headers.index("FlightNumber"), headers.index("Airport")
    pairs = []
    seen = set()
    for row in rows:
        flight = str(row[flight_idx]).strip() if flight_idx < len(row) else ""
        airport = str(row[airport_idx]).strip() if airport_idx < len(row) else ""
        pair = (flight, airport)
        if flight and airport and pair not in seen:
            pairs.append(pair)
            seen.add(pair)
    if pairs:
        return pairs

    # If the live sheet has no populated flight data yet, use the local synthetic
    # workshop workbook, never invent a real flight from participant feedback.
    sample_path = Path(DATA_FILE)
    if sample_path.exists():
        try:
            sample_df = pd.read_excel(sample_path)
            if {"FlightNumber", "Airport"}.issubset(sample_df.columns):
                for flight, airport in sample_df[["FlightNumber", "Airport"]].dropna().itertuples(index=False, name=None):
                    pair = (str(flight).strip(), str(airport).strip())
                    if all(pair) and pair not in seen:
                        pairs.append(pair)
                        seen.add(pair)
        except Exception:
            # A malformed/missing demo workbook should not prevent a workshop
            # submission; the clearly synthetic fallback below is safe.
            pass
    return pairs or [("AB101", "DOH")]


def next_flight_details(headers, rows):
    """Pick the next synthetic flight/airport pair in a repeatable rotation."""
    data_rows = _sheet_data_rows(rows)
    pairs = _flight_pairs(headers, data_rows)
    if not pairs:
        return {"FlightNumber": "AB101", "Airport": "DOH"}
    if "FlightNumber" in headers and "Airport" in headers:
        flight_idx, airport_idx = headers.index("FlightNumber"), headers.index("Airport")
        previous = None
        for row in reversed(data_rows):
            flight = str(row[flight_idx]).strip() if flight_idx < len(row) else ""
            airport = str(row[airport_idx]).strip() if airport_idx < len(row) else ""
            if flight and airport:
                previous = (flight, airport)
                break
        if previous in pairs:
            index = (pairs.index(previous) + 1) % len(pairs)
        else:
            index = 0
    else:
        index = 0
    flight, airport = pairs[index]
    return {"FlightNumber": flight, "Airport": airport}


def _validate_sheet_headers(headers):
    missing = REQUIRED_SHEET_HEADERS - set(headers)
    if missing:
        raise RuntimeError(
            "The Google Sheet is missing required headers: " + ", ".join(sorted(missing))
        )


def submit_feedback(customer_name, feedback, score, *, service=None, spreadsheet_url=None, sheet_name=None):
    """Validate a submission, auto-assign staff, and append one row to Google Sheets.

    The Sheets API append is protected by a process-local lock. For a multi-instance
    production deployment, a transactional database/queue would be needed to make
    staff round-robin assignment strictly concurrency-safe.
    """
    validated = validate_submission(customer_name, feedback, score)
    api = service or _sheets_service()
    sheet_id = spreadsheet_id_from_url(spreadsheet_url)
    sheet = sheet_name or SHEET_NAME

    with _SHEETS_LOCK:
        values = _read_sheet_values(api, sheet_id, sheet)
        if not values or not values[0]:
            raise RuntimeError(f"The Google Sheet tab '{sheet}' is empty; add its header row first.")
        headers = [str(value).strip() for value in values[0]]
        for header in AUTO_ADDED_HEADERS:
            headers = _add_header_if_missing(api, sheet_id, headers, header, sheet)
        _validate_sheet_headers(headers)

        staff_id_index = headers.index("StaffID")
        last_staff_id = ""
        for row in reversed(values[1:]):
            if staff_id_index < len(row) and str(row[staff_id_index]).strip():
                last_staff_id = str(row[staff_id_index]).strip()
                break
        staff = next_staff(last_staff_id)
        flight_details = next_flight_details(headers, values)
        record = build_submission_record(
            validated["CustomerName"], validated["CustomerComment"], validated["CSATScore"],
            staff=staff, flight_number=flight_details["FlightNumber"],
            airport=flight_details["Airport"],
        )
        row_values = [record.get(header, "") for header in headers]
        api.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=f"{_quoted_sheet_name(sheet)}!A:Z",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row_values]},
        ).execute()
    return {"success": True, "survey_id": record["SurveyID"], "staff_id": record["StaffID"],
            "staff_name": record["StaffName"], "category": record["Category"]}


def migrate_google_sheet_customer_names(*, service=None, spreadsheet_url=None, sheet_name=None,
                                        sample_file=None):
    """Add CustomerName and backfill historical workshop rows without overwriting names.

    Names are copied by SurveyID from the generated local sample workbook. If a row
    does not exist there, a neutral synthetic label is used rather than guessing a real
    customer identity. This function writes to the live Google Sheet when executed.
    """
    api = service or _sheets_service()
    sheet_id = spreadsheet_id_from_url(spreadsheet_url)
    sheet = sheet_name or SHEET_NAME
    with _SHEETS_LOCK:
        values = _read_sheet_values(api, sheet_id, sheet)
        if not values or not values[0]:
            raise RuntimeError(f"The Google Sheet tab '{sheet}' is empty; add its header row first.")
        headers = [str(value).strip() for value in values[0]]
        headers = _add_customer_name_header(api, sheet_id, headers, sheet)
        _validate_sheet_headers(headers)

        survey_id_index = headers.index("SurveyID")
        customer_index = headers.index("CustomerName")
        source_path = Path(sample_file or DATA_FILE)
        name_by_id = {}
        if source_path.exists():
            sample_df = pd.read_excel(source_path, sheet_name=sheet)
            if {"SurveyID", "CustomerName"}.issubset(sample_df.columns):
                name_by_id = {
                    str(row.SurveyID).strip(): str(row.CustomerName).strip()
                    for row in sample_df[["SurveyID", "CustomerName"]].itertuples(index=False)
                    if str(row.CustomerName).strip()
                }

        updates = []
        for row_number, row in enumerate(values[1:], start=2):
            current_name = str(row[customer_index]).strip() if customer_index < len(row) else ""
            if current_name:
                updates.append([current_name])
                continue
            survey_id = str(row[survey_id_index]).strip() if survey_id_index < len(row) else ""
            generated_name = name_by_id.get(survey_id) or f"Workshop Customer {row_number - 1:03d}"
            updates.append([generated_name])

        if updates:
            col = _column_letter(customer_index + 1)
            service_range = f"{_quoted_sheet_name(sheet)}!{col}2:{col}{len(updates) + 1}"
            api.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=service_range,
                valueInputOption="RAW",
                body={"values": updates},
            ).execute()
        return {"success": True, "historical_rows_checked": max(len(values) - 1, 0),
                "customer_names_filled": sum(
                    1 for row in values[1:]
                    if customer_index >= len(row) or not str(row[customer_index]).strip()
                ), "column_added": "CustomerName" not in [str(v).strip() for v in values[0]]}
