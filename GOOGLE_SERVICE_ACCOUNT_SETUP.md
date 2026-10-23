# Google service account setup (local Windows development)

1. Download the service account key as a `.json` file from Google Cloud Console.
2. In the root of this project (the folder containing `app.py`), create a folder named `secrets`.
3. Move the downloaded JSON file into that folder and rename it to `csat-feedback-writer.json`. Do not open it in an editor or share it.
4. Copy `.env.example` to `.env` if you have not already done so. Keep your existing settings. Set this line in `.env`:

   `GOOGLE_SERVICE_ACCOUNT_FILE=secrets/csat-feedback-writer.json`

5. The `.gitignore` file excludes the `secrets/` folder so the key is not committed to Git. Never upload the JSON key to GitHub or this chat.
6. Ensure `GOOGLE_SHEETS` API is enabled and the target spreadsheet is shared as Editor with the `client_email` value from the service account JSON. The app writes only to that spreadsheet using the Sheets API.

## Quick local check

Open a terminal in the project folder, activate your existing virtual environment, and run:

`python -c "from feedback_service import _load_service_account_info; d=_load_service_account_info(); print('Credential file loaded. Service account:', d.get('client_email', 'missing client_email'))"`

This check reads the local credential file only; it does not write to Google Sheets. If it prints the service account email, continue to the next connection test. Do not share the output of the key file itself; the email address alone is not a private key.
