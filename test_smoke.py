from pathlib import Path
from agent_core import load_excel, get_available_dates, analyze_day, google_download_url
from config import DATA_FILE

def test_sample_excel_loads():
    df = load_excel(DATA_FILE, "rowdata")
    assert len(df) > 0
    assert {"SurveyID", "SurveyDate", "StaffID", "StaffName", "Category", "CustomerComment", "CSATScore", "CustomerName"}.issubset(df.columns)
    assert df["CustomerName"].notna().all()
    assert df["CustomerName"].astype(str).str.strip().ne("").all()

def test_analysis_for_latest_date_without_llm():
    df = load_excel(DATA_FILE, "rowdata")
    day = get_available_dates(df)[-1]
    result = analyze_day(df, day, use_llm=False)
    assert result["metrics"]["survey_count"] > 0
    assert "staff_rankings" in result["payload"]
    assert "report_markdown" in result


def test_analysis_for_inclusive_date_range_without_llm():
    df = load_excel(DATA_FILE, "rowdata")
    dates = get_available_dates(df)
    result = analyze_day(df, (dates[0], dates[-1]), use_llm=False)
    assert result["metrics"]["survey_count"] == len(df)
    assert result["payload"]["report_period"] == f"{dates[0]} to {dates[-1]}"
    assert "Customer Feedback Report" in result["report_markdown"]


def test_analysis_rejects_reversed_date_range():
    import pytest
    df = load_excel(DATA_FILE, "rowdata")
    dates = get_available_dates(df)
    with pytest.raises(ValueError, match="Start date"):
        analyze_day(df, (dates[-1], dates[0]), use_llm=False)


def test_scheduler_requires_google_sheet_url_and_does_not_fall_back_to_local(monkeypatch):
    import run_daily
    monkeypatch.setattr(run_daily, "DRIVE_DOWNLOAD_URL", "")
    import pytest
    with pytest.raises(RuntimeError, match="Google Sheets source is not configured"):
        run_daily.resolve_data()


def test_google_sheets_link_converts_to_xlsx_export():
    url = "https://docs.google.com/spreadsheets/d/1z3A6J3TRsBjhLFtxwQ8n5_lG-TK77rfNzl8ySeye7rg/edit?gid=1562120834#gid=1562120834"
    assert google_download_url(url) == "https://docs.google.com/spreadsheets/d/1z3A6J3TRsBjhLFtxwQ8n5_lG-TK77rfNzl8ySeye7rg/export?format=xlsx"


def test_drive_file_link_converts_to_download_url():
    assert google_download_url("https://drive.google.com/file/d/abc_DEF-123/view") == "https://drive.google.com/uc?export=download&id=abc_DEF-123"


def test_load_google_sheet_uses_sheets_api_and_normalizes_rows(monkeypatch):
    import agent_core

    class FakeRequest:
        def execute(self):
            return {"values": [
                ["SurveyDate", "StaffID", "StaffName", "Category", "CustomerComment", "CSATScore", "SurveyID", "CustomerName"],
                ["2026-10-23", "S1001", "Amira Ben Salem", "Customer Service", "Helpful", "5", "FB-1", "Test Customer"],
            ]}
    class FakeValues:
        def get(self, **kwargs):
            assert kwargs["spreadsheetId"] == "sheet123"
            assert kwargs["range"] == "'rowdata'!A:Z"
            return FakeRequest()
    class FakeSpreadsheets:
        def values(self):
            return FakeValues()
    class FakeService:
        def spreadsheets(self):
            return FakeSpreadsheets()

    monkeypatch.setattr(agent_core, "_unused_for_test", None, raising=False)
    import feedback_service
    monkeypatch.setattr(feedback_service, "_sheets_service", lambda: FakeService())
    monkeypatch.setattr(feedback_service, "spreadsheet_id_from_url", lambda url: "sheet123")
    df = agent_core.load_google_sheet("https://docs.google.com/spreadsheets/d/sheet123/edit", "rowdata")
    assert len(df) == 1
    assert str(df.iloc[0]["SurveyDate"]) == "2026-10-23"
    assert df.iloc[0]["CustomerName"] == "Test Customer"
    assert df.iloc[0]["CSATScore"] == 5
