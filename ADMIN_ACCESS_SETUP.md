# Only the owner may administer the CSAT app

## Intended setup

- Public URL: `feedback_app.py` — colleagues can submit feedback.
- Private URL: `app.py` — only you can view CSAT records, manage recipients, ask data questions, and send reports.

## Streamlit Community Cloud steps

1. Leave your current participant app deployed with `feedback_app.py` as its main file and keep it public.
2. Create a second app from the same repository/branch. Set its main file to `app.py`.
3. After deployment, open the admin app's **⋮ → Settings → Sharing** (or **Share** from the app).
4. Set **Who can view this app** to **Only specific people can view this app** / make the app private.
5. Keep the access/viewer list limited to the account you use as the app owner. Do not invite colleagues as viewers or grant them GitHub developer permissions. Remove anyone unintended and save.
6. Keep Google credentials, Gmail credentials, and `RECIPIENTS_SPREADSHEET_URL` only in the admin app's Secrets when they are not needed by the participant form.
7. Test in a private/incognito browser window: participant URL should show the form; admin URL should require Streamlit access.

Streamlit Community Cloud documents a limit of one private app at a time. This design uses one public feedback app and one private admin app. If an uninvited account can view the admin app, stop and correct its Sharing settings before using admin features.

## Admin app secrets

Retain the real working values, using TOML syntax:

```toml
DRIVE_DOWNLOAD_URL = "https://docs.google.com/spreadsheets/d/YOUR_FEEDBACK_SPREADSHEET_ID/edit"
SHEET_NAME = "rowdata"
GOOGLE_SERVICE_ACCOUNT_JSON = '''
PASTE THE ENTIRE SERVICE ACCOUNT JSON HERE
'''
RECIPIENTS_SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_PRIVATE_RECIPIENTS_SPREADSHEET_ID/edit"
RECIPIENTS_SHEET_NAME = "recipient_lists"
GMAIL_ADDRESS = "youraddress@gmail.com"
GMAIL_APP_PASSWORD = "your-gmail-app-password"
SCHEDULER_TIMEZONE = "Asia/Qatar"
ENABLE_BACKGROUND_SCHEDULER = false
```

Do not commit secrets to GitHub or paste them into chat. Share the feedback workbook with the service account as Editor; share the separate private recipient workbook with the service account as Editor too. Report recipients themselves do not need Google Sheet access.
