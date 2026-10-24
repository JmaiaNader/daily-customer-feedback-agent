# Admin app navigation update

The admin interface now uses separate pages in the left navigation menu:

- **Chat assistant** — load live feedback, choose start/end dates, ask questions using example prompts, review answers as HTML, and share a result by email after confirmation. Full reports can still be previewed in HTML and explicitly sent.
- **AI Solution** — select survey dates and use local Gemma to add airline-specific issue categories, sentiment, root-cause hypotheses, and recommended actions to the displayed/exported rows.
- **Dashboard** — run CSAT analysis.
- **Data preview** — inspect or export loaded rows.
- **Settings** — configure per-session app options and create, update, or delete saved report recipient lists.
- **Scheduler** — set up scheduled reporting.

## Apply the update

1. Replace the repository's `app.py` with the updated `app.py` from this package.
2. Commit and push the change to the branch used by the private admin app on Streamlit Community Cloud.
3. Let the admin app redeploy, or reboot it from the Cloud dashboard.
4. Open the admin URL. Use the left-side **Open page** navigation to open **Chat assistant** or **AI Solution** first; other pages remain available below them.

The participant-facing `feedback_app.py` does not change and should remain deployed as its separate public app.

## Notes

- Recipient lists continue to use `RECIPIENTS_SPREADSHEET_URL` and `RECIPIENTS_SHEET_NAME` from the admin app's Secrets (or `.env` locally). The recipients themselves do not need access to the recipient spreadsheet.
- The app's adjustable source/model settings are saved in the current Streamlit session. For persistent deployment defaults, update the admin app's Secrets/environment values.
- The chat assistant still requires a refresh to fetch newly submitted live feedback before querying it.
- Keep the admin app restricted to your own account via Streamlit Community Cloud sharing controls.
