import pandas as pd
from insights_engine import build_csat_insights, insight_answer
from chat_assistant import answer_question


def sample_frame():
    return pd.DataFrame([
        {"SurveyID": "A1", "SurveyDate": "2026-10-20", "StaffID": "S1001", "StaffName": "Amira Ben Salem",
         "Category": "Baggage", "CustomerName": "Maya Ali", "CustomerComment": "My bag was delayed and nobody gave an update", "CSATScore": 1,
         "FlightNumber": "AB101", "Airport": "DOH"},
        {"SurveyID": "A2", "SurveyDate": "2026-10-21", "StaffID": "S1002", "StaffName": "Youssef Trabelsi",
         "Category": "Baggage", "CustomerName": "Maya Ali", "CustomerComment": "Still waiting for my luggage", "CSATScore": 2,
         "FlightNumber": "AB101", "Airport": "DOH"},
        {"SurveyID": "A3", "SurveyDate": "2026-10-22", "StaffID": "S1001", "StaffName": "Amira Ben Salem",
         "Category": "Check-in", "CustomerName": "Sami Test", "CustomerComment": "Very helpful", "CSATScore": 5,
         "FlightNumber": "AB102", "Airport": "TUN"},
        {"SurveyID": "A4", "SurveyDate": "2026-10-22", "StaffID": "S1003", "StaffName": "Sami Haddad",
         "Category": "Check-in", "CustomerName": "Nour Test", "CustomerComment": "Queue was long", "CSATScore": 2,
         "FlightNumber": "AB102", "Airport": "TUN"},
    ])


def test_insights_calculate_customer_impact_and_alerts():
    insights = build_csat_insights(sample_frame())
    assert insights["metrics"]["survey_count"] == 4
    assert insights["metrics"]["critical_score1_count"] == 1
    assert insights["metrics"]["low_score_count"] == 3
    assert insights["metrics"]["customers_with_low_scores"] == 2
    assert any(alert["severity"] == "CRITICAL" for alert in insights["alerts"])
    assert insights["recovery_queue"][0]["Priority"] == "CRITICAL"


def test_repeated_name_is_counted_once_for_customer_impact():
    insights = build_csat_insights(sample_frame())
    assert insights["metrics"]["customers_with_low_scores"] == 2  # Maya twice, Nour once
    baggage = next(row for row in insights["category_summary"] if row["Category"] == "Baggage")
    assert baggage["Named customers impacted"] == 1


def test_customer_impact_query_returns_named_recovery_queue():
    answer = answer_question(sample_frame(), "Which customers are impacted and need follow up?")
    assert "2 distinct named customer" in answer
    assert "Maya Ali" in answer
    assert "Nour Test" in answer


def test_alert_query_returns_actionable_evidence():
    answer = answer_question(sample_frame(), "What alerts and risks need attention?")
    assert "CRITICAL" in answer
    assert "score-1" in answer or "score-1" in answer.lower()
    assert "Recommended action" in answer


def test_executive_summary_query_includes_themes_and_actions():
    answer = answer_question(sample_frame(), "Give me an executive summary and recommended actions")
    assert "Executive summary" in answer
    assert "Baggage" in answer
    assert "Recommended next actions" in answer


def test_report_markdown_contains_customer_impact_and_alerts():
    from agent_core import analyze_day
    df = sample_frame()
    df["SurveyDate"] = pd.to_datetime(df["SurveyDate"]).dt.date
    result = analyze_day(df, (df["SurveyDate"].min(), df["SurveyDate"].max()), use_llm=False)
    assert "Executive Summary & Customer Impact" in result["report_markdown"]
    assert "Alerts & Recommended Actions" in result["report_markdown"]
    assert "Named customers impacted" in result["report_markdown"]


def test_combined_customer_impact_and_alert_question_returns_both():
    answer = answer_question(sample_frame(), "Which customers are impacted and what alerts should I see?")
    assert "Maya Ali" in answer
    assert "Related alerts" in answer
    assert "CRITICAL" in answer


def test_unique_customer_count_query_does_not_count_repeated_names_twice():
    answer = answer_question(sample_frame(), "How many unique customers submitted feedback?")
    assert "3 distinct named customer(s)" in answer
    assert "2 distinct named customer(s)" in answer


def test_category_why_question_returns_evidence_and_not_asserted_root_cause():
    answer = answer_question(sample_frame(), "Why is Baggage low CSAT?")
    assert "Baggage: evidence snapshot" in answer
    assert "My bag was delayed" in answer
    assert "not verified root causes" in answer


def test_chat_local_ollama_refuses_remote_endpoint(monkeypatch):
    import chat_assistant
    monkeypatch.setattr(chat_assistant, "OLLAMA_URL", "https://ollama.com")
    def should_not_call(*args, **kwargs):
        raise AssertionError("remote API must not be called")
    monkeypatch.setattr(chat_assistant.requests, "post", should_not_call)
    answer = chat_assistant._local_ollama_answer(sample_frame(), "What happened?")
    assert answer is None


def test_report_analysis_refuses_remote_ollama_endpoint(monkeypatch):
    import agent_core
    monkeypatch.setattr(agent_core, "OLLAMA_URL", "https://ollama.com")
    def should_not_call(*args, **kwargs):
        raise AssertionError("remote Ollama endpoint must not be called")
    monkeypatch.setattr(agent_core.requests, "post", should_not_call)
    import pytest
    with pytest.raises(RuntimeError, match="Local Ollama only"):
        agent_core._ollama_analysis([], model="gemma3:4b")


def test_interpretive_question_can_add_local_ollama_narrative_without_changing_evidence(monkeypatch):
    import chat_assistant
    def fake_local(df, question, model=None, deterministic_evidence=None):
        assert "Baggage: evidence snapshot" in deterministic_evidence
        return "The comments suggest delays may be a recurring experience; validate operational timestamps."
    monkeypatch.setattr(chat_assistant, "_local_ollama_answer", fake_local)
    answer = chat_assistant.answer_question(sample_frame(), "Why is Baggage low CSAT?", use_llm=True)
    assert "Baggage: evidence snapshot" in answer
    assert "Local Ollama interpretation" in answer
    assert "validate operational timestamps" in answer
