# Gemma AI reasoning update

## What changed

- The Chat assistant routes interpretive questions (for example, "Why did CSAT decline in this period?") to the configured local Ollama model before returning a simple KPI-only answer.
- The local-model prompt includes dates, scores, source categories, comments, daily trends, and—when present—`AI_Category`, `primary_issue`, `secondary_issue`, `sentiment`, `root_cause_hypothesis`, and `recommended_action`.
- The prompt asks the model to distinguish observed evidence, root-cause hypotheses, management actions, and data limitations. When no prior-period baseline is available, it must not claim a decline relative to the previous period is proven.
- The analysis prompt is compacted for local performance: full-period aggregates are retained, while up to 20 representative comments are passed to Gemma (low-score comments prioritized, with other scores retained for contrast). Comments and AI text fields are length-limited, the prompt context is capped at 4,096 tokens, the answer is limited to 600 generated tokens, and the request may take up to 180 seconds. `keep_alive` asks Ollama to keep the model loaded for 10 minutes to avoid repeated unload/reload overhead.
- If AI analysis is disabled, unreachable, times out, or fails, the answer says explicitly that it is Python-only. Python KPI calculations are never presented as an AI interpretation.
- The AI Solution page now adds a Gemma chat section below the date-filtered AI-enriched table. It includes sample questions, an HTML answer preview, and a reviewed/confirmed email-sharing flow using the saved recipient lists.
- The AI Solution analysis is based on the displayed AI-enriched table, including the added airline category and interpretation columns. The original Google Sheet remains unchanged; CSV export is available.

## Running locally

1. Start Ollama and ensure the model is installed: `ollama run gemma3:4b`.
2. Run the private admin app on the same laptop: `streamlit run app.py`.
3. In Settings, enable local Ollama and confirm the model name is `gemma3:4b`.
4. In Chat assistant, load feedback, select dates, then ask an interpretive question such as `Why did CSAT decline in this period?`.
5. In AI Solution, load rows, choose dates, run Gemma row analysis, and ask a question below the results table.

## Important interpretation rule

Python is used for reliable aggregate calculations. Gemma is used for language interpretation and recommendations. Root-cause outputs are hypotheses that management must validate against airline operational data such as flight disruption logs, queue times, refund timelines, and service-handling records.

This app intentionally uses local Ollama only. A Streamlit Cloud server cannot connect to Ollama running on a personal laptop's localhost.
