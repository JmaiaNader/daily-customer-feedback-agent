# Styled HTML email reports

Email reports use `email_report.py` to create a responsive, email-client-friendly HTML report. The message includes KPI cards, an executive summary, colored priority alerts, bar-chart visualizations, category/staff tables, the customer-recovery queue, feedback theme signals, interpretations, and recommended next actions.

## Compatibility design

The charts are drawn as table-based colored bars with inline styles. This is intentional: email clients such as Gmail and Outlook frequently block external images, CSS files, JavaScript, and interactive Plotly charts. No remote images are required. The email has both `text/plain` and `text/html` alternatives, so recipients with HTML disabled still receive the text report.

## Where this applies

- Dashboard: preview and send a styled report to a typed recipient.
- Chat assistant: preview the same styled report, select a recipient list, and explicitly confirm email delivery.
- Scheduler: sends the styled HTML report using the configured recipient list.
- `run_daily.py`: sends the styled HTML report for its scheduled date.

The report HTML is also saved alongside Markdown and JSON when `save_report()` is called. All customer-supplied text is HTML-escaped before rendering.

## Validation

`test_email_report.py` verifies that the output contains the key sections and charts, that customer text is escaped, that a minimal report can render, and that Gmail sending produces a multipart alternative message. Tests mock SMTP and do not send a real email.
