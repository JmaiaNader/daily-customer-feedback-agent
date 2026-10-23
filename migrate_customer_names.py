"""One-time Google Sheet migration for the workshop CustomerName column.

Run from the project directory after configuring GOOGLE_SERVICE_ACCOUNT_JSON:
    python migrate_customer_names.py
This writes to the configured live Google Sheet. Verify DRIVE_DOWNLOAD_URL and
share the sheet with the service account as an Editor before running it.
"""
from feedback_service import migrate_google_sheet_customer_names


if __name__ == "__main__":
    result = migrate_google_sheet_customer_names()
    print("Google Sheet CustomerName migration complete:")
    for key, value in result.items():
        print(f"- {key}: {value}")
