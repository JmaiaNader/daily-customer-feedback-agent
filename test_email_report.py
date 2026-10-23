import pandas as pd

from agent_core import analyze_day
from email_report import render_html_report


def _sample_report():
    df = pd.DataFrame([
        {"SurveyID": "E1", "SurveyDate": "2026-10-20", "StaffID": "S1001", "StaffName": "Amira Ben Salem",
         "Category": "Baggage", "CustomerName": "Maya Ali", "CustomerComment": "Bag delayed <please call>", "CSATScore": 1,
         "FlightNumber": "AB101", "Airport": "DOH"},
        {"SurveyID": "E2", "SurveyDate": "2026-10-21", "StaffID": "S1002", "StaffName": "Youssef Trabelsi",
         "Category": "Baggage", "CustomerName": "Nour Ali", "CustomerComment": "No update from the team", "CSATScore": 2,
         "FlightNumber": "AB101", "Airport": "DOH"},
        {"SurveyID": "E3", "SurveyDate": "2026-10-22", "StaffID": "S1003", "StaffName": "Sami Haddad",
         "Category": "Check-in", "CustomerName": "Amina Test", "CustomerComment": "Very helpful service", "CSATScore": 5,
         "FlightNumber": "AB102", "Airport": "TUN"},
    ])
    df["SurveyDate"] = pd.to_datetime(df["SurveyDate"]).dt.date
    return analyze_day(df, (df["SurveyDate"].min(), df["SurveyDate"].max()), use_llm=False)


def test_email_html_includes_kpis_charts_tables_alerts_and_actions():
    report = _sample_report()
    html = render_html_report(report["payload"])
    for text in [
        "Customer Feedback Report", "AVERAGE CSAT", "CSAT score distribution",
        "Categories contributing to low CSAT", "Staff CSAT comparison",
        "Daily CSAT trend", "Category performance table", "Staff performance table",
        "Customer recovery queue", "Alerts &amp; priorities", "Recommended next actions",
    ]:
        assert text in html
    assert html.count("<table") == html.count("</table>")
    assert "https://" not in html  # no remote image/asset dependencies


def test_email_html_escapes_customer_supplied_text():
    html = render_html_report(_sample_report()["payload"])
    assert "&lt;please call&gt;" in html
    assert "<please call>" not in html


def test_email_renderer_handles_minimal_payload():
    html = render_html_report({
        "report_date": "2026-10-23",
        "metrics": {"survey_count": 0, "average_csat": 0, "positive_rate_pct": 0, "low_rate_pct": 0},
        "cx_insights": {"metrics": {"survey_count": 0}, "alerts": [], "data_quality_notes": []},
        "ai_analysis": {},
    })
    assert "2026-10-23" in html
    assert "CSAT score distribution" in html


def test_send_gmail_builds_multipart_html_email_without_sending_real_email(monkeypatch):
    import agent_core
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, context=None, timeout=None):
            assert host == "smtp.gmail.com"
            assert port == 465
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def login(self, sender, password):
            assert sender == "sender@example.com"
            assert password == "app-password"
        def send_message(self, msg):
            captured["message"] = msg

    monkeypatch.setattr(agent_core, "GMAIL_ADDRESS", "sender@example.com")
    monkeypatch.setattr(agent_core, "GMAIL_APP_PASSWORD", "app-password")
    monkeypatch.setattr(agent_core.smtplib, "SMTP_SSL", FakeSMTP)

    agent_core.send_gmail(
        "recipient@example.com", "CSAT report", "Plain text fallback",
        html_body="<html><body><h1>Styled report</h1></body></html>",
    )
    message = captured["message"]
    assert message.get_content_type() == "multipart/alternative"
    parts = list(message.iter_parts())
    assert parts[0].get_content_type() == "text/plain"
    assert "Plain text fallback" in parts[0].get_content()
    assert parts[1].get_content_type() == "text/html"
    assert "Styled report" in parts[1].get_content()
