# Streamlit Community Cloud deployment notes

## Deploy the UI

1. Push the project to a private/public GitHub repository (only if its data and code are safe to share). Never commit `.env`, `.streamlit/secrets.toml`, service-account JSON files, passwords, or customer data.
2. In Streamlit Community Cloud, create an app from the repository and select `app.py` as the entry point.
3. Add the dependencies from `requirements.txt` (Cloud does this during deploy).
4. In App settings → Secrets, copy the relevant keys from `.streamlit/secrets.example.toml` and replace every example value. `GMAIL_APP_PASSWORD` must be a Google App Password, not your normal Gmail password.
5. Set `ENABLE_BACKGROUND_SCHEDULER = false` on Community Cloud. The Scheduler page remains available for configuration and manual testing.


## Admin dashboard, recipient lists, chat, and report email

The public participant form remains `feedback_app.py`. Deploy `app.py` as a separate admin app if you want an online dashboard. Access to the admin app should be restricted using Streamlit Community Cloud private-app sharing settings. There is no separate in-app admin password.

The admin app adds a `Chat & recipients` tab:

- A Python-backed query assistant can answer supported questions about counts, average CSAT, low/positive scores, categories, staff summaries, recent comments, and daily trends. It computes numbers from the loaded data rather than asking an LLM to invent them.
- Asking to prepare or send a report creates a Python-only report preview for the selected date range. It is **not sent automatically**; a signed-in admin must select a recipient list, review the preview, tick the confirmation box, and press **Send report by Gmail**.
- Recipient lists can be created, replaced/edited by saving the same list name, and deleted. The same lists are used by scheduled report configuration.

### Keep email addresses private

If the feedback workbook is publicly viewable, **do not store recipient email addresses in another tab of that workbook**. Create a separate Google spreadsheet for recipient management and keep its sharing restricted. Share that private recipient spreadsheet with the same service-account email as **Editor**. Set these keys in Streamlit Community Cloud → App settings → Secrets (or in `.env` locally):

```toml
RECIPIENTS_SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_PRIVATE_RECIPIENTS_SPREADSHEET_ID/edit"
RECIPIENTS_SHEET_NAME = "recipient_lists"
```

The first successful save automatically creates the `recipient_lists` tab if it does not exist. The tab uses two columns: `ListName` and `Email`. Do not make this separate workbook public. Configure `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` as well before sending email; use a Gmail App Password, not the regular Gmail account password. The Google Sheets service-account JSON remains in Streamlit Secrets under `GOOGLE_SERVICE_ACCOUNT_JSON` and must never be committed to GitHub.

On Streamlit Community Cloud, after updating these Secrets, save the settings and restart/redeploy the app so `config.py` reloads them.

## Google Drive access

- For a deliberately public/demo spreadsheet, set `DRIVE_DOWNLOAD_URL` in secrets; Google Sheets API access is used. The code no longer contains a hard-coded spreadsheet ID fallback; configure the URL in `.env` or Streamlit Secrets.
- For private Drive/Sheets data, set `GOOGLE_SERVICE_ACCOUNT_JSON` to the service account JSON as a TOML multiline string and share the source file with the service account's `client_email` as Viewer. The app uses read-only Drive API access. Do not commit the JSON key. In a managed company environment, prefer a company-approved identity/secret manager.
- A URL is configuration, not an authentication credential. A private URL by itself does not grant access.

## Email credentials

Store `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in Streamlit Secrets. Do not use a normal Gmail password or hardcode either value. The private `RECIPIENTS_SPREADSHEET_URL` is the persistent source for named recipient lists; the legacy `[recipient_lists]` Secrets table is only a fallback for older setups.

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


## Admin-only access model (important)

Deploy `feedback_app.py` as the public participant form and deploy `app.py` as a **separate private admin app**. In Streamlit Community Cloud, open the admin app's **Settings → Sharing** and choose **Only specific people can view this app**. Keep its viewer list limited to your own account; do not invite participants or colleagues and do not grant them GitHub developer access. Do not add a separate in-app password; Streamlit's private-app access is the control.

Community Cloud currently permits only one private app at a time; this setup uses one public feedback app plus one private admin app. Check the admin app's sharing setting after deployment. See `ADMIN_CHAT_DEPLOYMENT.md` for exact deployment and per-app Secrets steps.
