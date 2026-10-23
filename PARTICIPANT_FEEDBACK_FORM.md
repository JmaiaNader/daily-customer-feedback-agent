# Participant Feedback Form

The project now includes a separate participant-facing Streamlit app. Keep the existing `app.py` as the admin/analysis dashboard; participants should use `feedback_app.py` so they do not see the reporting tools or scheduler.

## Run locally

1. Open a terminal in the project directory (the same directory that contains `feedback_app.py`).
2. Activate the existing virtual environment.
3. Confirm `.env` contains your configured Google Sheets URL, sheet tab name, and service-account key path. For example:

   ```dotenv
   DRIVE_DOWNLOAD_URL=https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit
   SHEET_NAME=rowdata
   GOOGLE_SERVICE_ACCOUNT_FILE=secrets/csat-feedback-writer.json
   ```

4. Confirm the JSON key file exists at `secrets/csat-feedback-writer.json`, and that the converted native Google Sheet is shared with the service account as Editor.
5. Install dependencies if needed:

   ```powershell
   pip install -r requirements.txt
   ```

6. Start the participant app:

   ```powershell
   streamlit run feedback_app.py
   ```

Streamlit prints a local URL (normally `http://localhost:8501`). Open it in your browser.

## Participant experience

The form asks for exactly three inputs: name, feedback text, and CSAT score from 1 to 5. After valid submission, the backend appends the record to the configured `rowdata` tab and confirms the generated survey reference. It generates the survey ID and date, classifies feedback with local Python keyword rules, assigns staff in rotation, and populates the synthetic workshop flight/airport values. The submission path does not call Ollama.

## Sharing the app

Running locally makes the form available on the host computer, not automatically to other participants. To let participants use their own devices, deploy the participant app to a trusted hosting environment and configure the Google service-account key as a private server-side secret. Never commit the `.env` file or service-account JSON to source control, and do not give participants access to the admin app or the service-account key. Test the deployed app using a test record before sharing the URL broadly.

The sample flight/airport fields are synthetic workshop metadata, not verified customer travel records. If this becomes a real operational CSAT system, replace the automatic demo assignment with reliable source data before relying on flight/airport analytics.


### Dashboard data source
The dashboard and scheduler now read the live native Google Sheet directly through the configured Google service account and Google Sheets API. Set `DRIVE_DOWNLOAD_URL` to the converted spreadsheet URL and `SHEET_NAME=rowdata` in `.env`. The service account must have Editor access to the spreadsheet.
