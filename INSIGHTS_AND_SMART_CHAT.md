# CSAT Dashboard Insights & Smarter Chat

This update adds a shared insight report to both the **Dashboard** and **Chat assistant** pages.

## What's new

- Executive summary and KPI row: survey count, average CSAT, positive rate, low-CSAT count/rate, and distinct named customers represented in low-score cases.
- Priority alerts: score-1 cases, elevated low-CSAT concentration, repeated low-score issue categories, and conservative recent CSAT declines when enough data exists.
- Interactive Plotly charts: score distribution, daily CSAT trend, category impact, and staff CSAT with survey-volume context.
- Detail tables: categories, staff comparisons, low-score customer recovery queue, and keyword signals in low-score comments.
- Recovery queue export to CSV.
- Reports/email preview now include executive summary, alerts/action recommendations, category/customer-impact table and text-signal summary.
- More capable chat queries using computed values: customer impact/recovery, score-1 alerts, risks, executive summary, recommended actions, category-specific explanations, and flight/airport issues.
- Optional local Ollama interpretation for insight/why/recommendation questions, plus fallback for free-form questions the deterministic query tools cannot map.

## What the metrics mean

- **Low CSAT** means a CSAT score of 1 or 2.
- **Customers impacted** is the count of distinct non-empty `CustomerName` values among low-CSAT records. It is not a verified unique-customer count because this schema does not have a stable customer ID. If a name appears multiple times it is counted once; records with unknown/blank names are excluded from the named-customer count.
- A score of 1 raises a critical recovery alert.
- The low-CSAT alert is High at 20% or more of responses or at least three low-score records, Medium at 10% or more, and Info for a smaller non-zero low-score share.
- A category alert requires at least two low-score records and at least 40% of all low-score records in the selected period.
- The recent-deterioration alert compares volume-weighted averages across recent date windows and requires enough records to reduce noise.
- Theme matches use transparent keyword rules. They are signals to review—not proven root causes.

## AI / Ollama behavior

- Python calculates numeric metrics, counts, alerts and tables; these are the source of truth.
- The comment-analysis expander can use Ollama for narrative interpretation if a **local** Ollama instance is reachable at `http://localhost:11434` (or another loopback URL).
- Remote Ollama APIs are explicitly not used.
- On Streamlit Community Cloud, `localhost` refers to the cloud container, not the user's laptop. The cloud app therefore shows the Python-computed insights and will fall back when local Ollama is unavailable. To use actual local-model commentary, run the admin app on the same computer where Ollama is running. An online LLM would require a separate hosted model, which is outside this local-only configuration.
- The model receives a bounded set of records only when the user enables local Ollama; prompts treat comment text as untrusted data. It cannot send email. Report sending still requires review and an explicit confirmation in the interface.

## Deploy the update

1. Replace the files in your existing GitHub repository with this project version; do not overwrite real `.env` files or service-account keys.
2. Ensure `requirements.txt` includes `plotly>=5.24`.
3. Commit and push to the branch used by your admin Streamlit app and let it redeploy.
4. On **Dashboard**, click **Load data**, choose a date range and click **Analyze selected date range**.
5. On **Chat assistant**, click **Refresh live feedback data**, choose the same or a different date range, then ask questions. Example prompts:
   - `Which customers need recovery follow-up?`
   - `Show customer impact by category.`
   - `What alerts and risks need attention?`
   - `Which customers are impacted by baggage issues?`
   - `Why is Baggage low CSAT?`
   - `Which flights or airports have the most low-CSAT records?`
   - `Give me an executive summary and recommended actions.`
   - `Prepare a report for this date range.`
6. When a report is ready, review it, choose a saved recipient list, and confirm before sending. The assistant never sends mail just because a question mentions email.

## Validation

The automated test suite includes checks for customer-impact counts, alerts, category evidence, report sections, and guarding against remote Ollama endpoints.


All 54 automated tests passed for this package. Streamlit UI rendering itself should still be smoke-tested after redeploying because the packaging environment used syntax checks and the Python test suite rather than a live hosted browser session.


## Styled HTML email reports

Email sending now uses `email_report.py` to render the same report payload in an organized HTML layout: colored KPI cards, a summary, colored alerts, email-safe bar charts, category and staff tables, a customer recovery queue, text signals, and recommended actions. The message includes a plain-text alternative, and uses inline styles/table-based bars rather than remote images, so it remains readable in Gmail and Outlook. The dashboard and chat report previews now display the styled email before sending. See `HTML_EMAIL_REPORTS.md` for details.
