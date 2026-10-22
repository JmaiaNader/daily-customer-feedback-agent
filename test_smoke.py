from pathlib import Path
from agent_core import load_excel, get_available_dates, analyze_day, google_download_url
from config import DATA_FILE

def test_sample_excel_loads():
    df = load_excel(DATA_FILE, "rowdata")
    assert len(df) > 0
    assert {"SurveyID", "SurveyDate", "StaffID", "StaffName", "Category", "CustomerComment", "CSATScore"}.issubset(df.columns)

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


def test_scheduler_requires_google_drive_and_does_not_fall_back_to_local(monkeypatch):
    import run_daily
    called = {"drive": 0}
    def fake_drive_download():
        called["drive"] += 1
        raise RuntimeError("Google Drive not configured")
    monkeypatch.setattr(run_daily, "download_google_drive_excel", fake_drive_download)
    import pytest
    with pytest.raises(RuntimeError, match="Google Drive not configured"):
        run_daily.resolve_data_file()
    assert called["drive"] == 1


def test_google_sheets_link_converts_to_xlsx_export():
    url = "https://docs.google.com/spreadsheets/d/1V9pm0CqemhWb-wwzcMYrPln4WPdIpiX9/edit?gid=1633225144#gid=1633225144"
    assert google_download_url(url) == "https://docs.google.com/spreadsheets/d/1V9pm0CqemhWb-wwzcMYrPln4WPdIpiX9/export?format=xlsx"


def test_drive_file_link_converts_to_download_url():
    assert google_download_url("https://drive.google.com/file/d/abc_DEF-123/view") == "https://drive.google.com/uc?export=download&id=abc_DEF-123"
