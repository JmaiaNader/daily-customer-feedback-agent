# CustomerName column — workshop migration

The sample workbook at `data/sample_surveys.xlsx` now includes a `CustomerName` column immediately before `CustomerComment`. All 26 historical sample rows have synthetic customer names for workshop demonstrations; these are not real customer identities.

## Live Google Sheet

The workbook in this repository is the local sample file. Editing it does **not** change the live Google Sheet stored in Drive. Before using the future feedback-submission form against the live sheet:

1. Add a column with the exact header `CustomerName` immediately before `CustomerComment`.
2. Populate existing historical rows only with approved/demo names. Do not infer real customer names from comments.
3. Keep `CustomerName` populated on each new form submission.

The current data loader remains backward-compatible with older workbooks that do not yet have `CustomerName`; such rows are represented as `Unknown Customer` until the live data is migrated. The current Drive flow downloads data for analysis and does not write changes back to the live sheet.


A one-time live Google Sheet migration script is now included: `python migrate_customer_names.py`.
It adds `CustomerName` at the end of the live header row if missing and fills only blank historical cells, matching `SurveyID` to the generated local sample workbook or using neutral `Workshop Customer NNN` labels when there is no match. It does not overwrite existing non-empty values. Review your configured sheet URL and service-account Editor access before running it.
