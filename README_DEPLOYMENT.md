# Streamlit Community Cloud deployment notes

## Deploy the UI

1. Push the project to a private/public GitHub repository (only if its data and code are safe to share). Never commit `.env`, `.streamlit/secrets.toml`, service-account JSON files, passwords, or customer data.
2. In Streamlit Community Cloud, create an app from the repository and select `app.py` as the entry point.
3. Add the dependencies from `requirements.txt` (Cloud does this during deploy).
4. In App settings → Secrets, copy the relevant keys from `.streamlit/secrets.example.toml` and replace every example value. `GMAIL_APP_PASSWORD` must be a Google App Password, not your normal Gmail password.
5. Set `ENABLE_BACKGROUND_SCHEDULER = false` on Community Cloud. The Scheduler page remains available for configuration and manual testing.

## Google Drive access

- For a deliberately public/demo spreadsheet, set `DRIVE_DOWNLOAD_URL` in secrets; Google Sheets API access is used.
- For private Drive/Sheets data, set `GOOGLE_SERVICE_ACCOUNT_JSON` to the service account JSON as a TOML multiline string and share the source file with the service account's `client_email` as Viewer. The app uses read-only Drive API access. Do not commit the JSON key. In a managed company environment, prefer a company-approved identity/secret manager.
- A URL is configuration, not an authentication credential. A private URL by itself does not grant access.

## Email credentials

Store `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in Streamlit Secrets. Do not use a normal Gmail password or hardcode either value. Configure named lists under `[recipient_lists]`; each list is an array of email addresses. A list selected in the Scheduler page determines the scheduled email recipients.

## Scheduler reliability limitation (important)

A background thread inside a Streamlit app is not a reliable production scheduler on Community Cloud: the app can sleep, restart, redeploy, or run more than one instance. Its local JSON config/status files may also be lost on restart. Therefore this project intentionally does **not** start automatic background jobs on Cloud by default. The UI can save configuration and run a report manually, but it must not be treated as guaranteed unattended delivery on Community Cloud.

Smallest sensible production workaround:

1. Keep Streamlit as the UI.
2. Move schedule configuration and run history to a durable store (e.g. a small Postgres/Supabase table).
3. Run the same `scheduler_service.run_scheduled_job` logic from an external scheduled worker (GitHub Actions, a managed cron service, or Cloud Scheduler + a small worker). The worker should read the same durable configuration, use the same secrets, and use a database lock/idempotency key so retries or multiple instances cannot send duplicates.

For a simple local desktop/server deployment, set `ENABLE_BACKGROUND_SCHEDULER=true`; keep the process running. The scheduler has a process-level overlap guard and persists a visible last-run status locally. For production, use a durable distributed lock instead of relying on a process-level lock.

## Current assumptions and limits

- `Once` means one run at the next configured run time; `Daily` means every day; `Repeat N times` means one attempt per day until N attempts have been made.
- A failed attempt is counted toward the repeat limit to avoid an indefinitely failing schedule. The UI shows the failure and no success is recorded unless email sending succeeds.
- The scheduler always reads the configured Google Drive workbook, never the laptop upload or sample workbook.
- Scheduled Ollama analysis is off by default because a local `localhost` Ollama service is not available from Streamlit Cloud. Enable it only if the app can reach a hosted Ollama endpoint.
- Local `scheduler_config.json` and `logs/scheduler_status.json` are for local use/demo only and are not durable storage on Community Cloud.
