# CSAT feedback form + administrator-only dashboard

This project is intended to run as **two separate Streamlit Community Cloud apps**:

- `feedback_app.py`: the public participant form. Colleagues can submit only their name, feedback, and CSAT score.
- `app.py`: the admin dashboard. Only the owner/admin should be able to access it. It includes CSAT analysis, chat queries, recipient-list management, and report email.

## Critical access-control rule: make only the admin app private

A password field inside the app is an extra layer, not the main access control. Restrict access at the Streamlit hosting layer too.

1. Deploy the participant app using `feedback_app.py` as its **Main file path**. In its app settings, set **Sharing → Who can view this app → This app is public and searchable** (or the equivalent public option). This is the only app URL you share with participants.
2. Create a **second app** from the same repository and branch, using `app.py` as its **Main file path**.
3. Open the admin app's Streamlit Community Cloud page. Select **⋮ → Settings → Sharing** (or open **Share** in the running app).
4. Set **Who can view this app** to **Only specific people can view this app** / make the app private.
5. Keep the viewer list limited to you. Do **not** invite colleagues as viewers and do not add them as GitHub developers/collaborators unless you explicitly intend to give them admin access. Remove any unintended viewers, then save.

Streamlit Community Cloud currently allows only **one private app at a time**. This design uses the public participant form and one private admin app. Confirm the privacy status in the admin app's Sharing settings before using recipient management or report sending.

## Deploy the two apps

For each app, use Streamlit Community Cloud → **Create app** and select the same repository and branch:

- Participant app main file: `feedback_app.py`
- Admin app main file: `app.py`

Each deployed app has its own **Settings → Secrets**. Do not assume secrets from one app automatically transfer to the other.

## Secrets for the public participant app

Add only the settings it needs to append feedback to the live workbook:

```toml
DRIVE_DOWNLOAD_URL = "https://docs.google.com/spreadsheets/d/YOUR_FEEDBACK_SPREADSHEET_ID/edit"
SHEET_NAME = "rowdata"
GOOGLE_SERVICE_ACCOUNT_JSON = '''
PASTE THE COMPLETE SERVICE-ACCOUNT JSON HERE
'''
```

Replace the URL and JSON with your actual values. Keep the entire JSON inside the triple-single-quoted TOML string. Never commit the JSON, `.env`, or real `secrets.toml` to GitHub. Share the feedback spreadsheet with the `client_email` from that JSON as Editor so the form can append rows.

Do not add `RECIPIENTS_SPREADSHEET_URL`, `GMAIL_APP_PASSWORD`, or other report-management secrets to the participant app unless that app specifically requires them. Keep the public interface limited to feedback submission.

## Secrets for the private admin app

Add these in the **admin app's own** Settings → Secrets. Retain your real working values for `DRIVE_DOWNLOAD_URL`, `SHEET_NAME`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GMAIL_ADDRESS`, and `GMAIL_APP_PASSWORD`.

```toml
DRIVE_DOWNLOAD_URL = "https://docs.google.com/spreadsheets/d/YOUR_FEEDBACK_SPREADSHEET_ID/edit"
SHEET_NAME = "rowdata"
GOOGLE_SERVICE_ACCOUNT_JSON = '''
PASTE THE COMPLETE SERVICE-ACCOUNT JSON HERE
'''

RECIPIENTS_SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_PRIVATE_RECIPIENTS_SPREADSHEET_ID/edit"
RECIPIENTS_SHEET_NAME = "recipient_lists"
GMAIL_ADDRESS = "youraddress@gmail.com"
GMAIL_APP_PASSWORD = "your-gmail-app-password"
SCHEDULER_TIMEZONE = "Asia/Qatar"
ENABLE_BACKGROUND_SCHEDULER = false
```

Replace all placeholders. Keep the recipient spreadsheet private and share it with the configured service account as Editor. Do not make that workbook public, and do not add report recipients as Google Sheet editors merely so they can receive emails.

`GMAIL_APP_PASSWORD` must be a Gmail App Password, not your normal Gmail password. Do not paste real credentials into chat or source code.

## Recipient lists and report sending

The admin dashboard can create/update a named list by saving the same list name, and delete a list. The first successful save creates a `recipient_lists` tab in the separate private workbook with `ListName` and `Email` columns.

The chat assistant calculates supported metrics using Python against the loaded data. Asking it to prepare or send a report creates a report preview, but **does not send the email automatically**. Sending requires choosing a saved recipient list, reviewing the report, ticking confirmation, and clicking **Send report by Gmail**.

## Verify admin-only access before using it

- Open the participant URL in a private/incognito browser window. It should show the feedback form.
- Open the admin URL in a private/incognito browser window while signed out of Streamlit. It should require Streamlit account access and should not be viewable just by knowing the URL.
- The admin app relies on Streamlit Community Cloud private-app access. No separate in-app password is required.
- Never share the admin URL and password together, and never invite participants to the private admin app.

If the admin page can be opened by an uninvited account, stop and correct the app's Sharing settings before using it.
