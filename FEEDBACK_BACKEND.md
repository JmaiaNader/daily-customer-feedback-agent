# Workshop feedback backend

This change adds a backend submission service without replacing the current Streamlit dashboard, reports, scheduler, or local Ollama analysis.

## Participant fields

The separate participant app (`feedback_app.py`) asks only for `CustomerName`, `CustomerComment`, and `CSATScore` (integer 1–5). The backend generates `SurveyID` and `SurveyDate`, classifies the category with transparent local keyword rules, assigns a staff member in round-robin order, and sets `Channel` to `Workshop Feedback Form`. `SurveyDate` is stored as a date only (`YYYY-MM-DD`), without a time component. `FlightNumber` and `Airport` are auto-assigned by rotating through distinct pairs already present in the synthetic workshop history (for this sample, `AB101`–`AB126` and `DOH`). These are workshop/demo assignments and must not be interpreted as real journey details. `Language` remains blank because no reliable source or rule is defined. The submission path does not call Ollama.

Workshop staff rotation:

- `S1001` — Amira Ben Salem
- `S1002` — Youssef Trabelsi
- `S1003` — Sami Haddad

The next staff member is chosen from the last recorded `StaffID` in the sheet. If the last historical staff ID is not one of these workshop staff IDs, the first workshop staff member is used for the first new submission.

## Configure Google Sheets write access

The project reuses `DRIVE_DOWNLOAD_URL`, `SHEET_NAME`, and `GOOGLE_SERVICE_ACCOUNT_JSON`. For writes:

1. Enable the Google Sheets API in the Google Cloud project that owns the service account.
2. Share the existing Google spreadsheet with the service account's `client_email` and grant **Editor** access.
3. Put the complete service-account JSON in local `.env` as `GOOGLE_SERVICE_ACCOUNT_JSON` or in Streamlit Secrets. Do not commit credentials.
4. Verify `DRIVE_DOWNLOAD_URL` points to the intended Google spreadsheet and `SHEET_NAME` is the correct tab (default `rowdata`).

The Sheet needs the existing headers `SurveyID`, `SurveyDate`, `StaffID`, `StaffName`, `Category`, `CustomerComment`, and `CSATScore`. If `CustomerName`, `FlightNumber`, or `Airport` is missing, the backend adds that column at the end without shifting existing columns. New submission rows are built by header name, so their column order can vary.

## One-time historical migration

The local sample workbook already includes synthetic `CustomerName` values. To add the column to the live Google Sheet and backfill empty historical names by `SurveyID` from that workbook, run:

```bash
python migrate_customer_names.py
```

This is a write operation on the configured live Google Sheet. Review the URL and service account permissions first. Historical IDs that do not match the local sample workbook are labeled `Workshop Customer 001`, etc.; the script does not infer real identities from comments and does not overwrite existing non-empty customer names.

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q
```

The submission service is available through `feedback_service.submit_feedback(...)`. The participant-facing Streamlit form is a separate app: launch it with `streamlit run feedback_app.py`. Submission write access and staff round-robin are designed for a single workshop app process. For simultaneous submissions across multiple app instances, use a transactional database or queue for strictly concurrency-safe staff assignment.
