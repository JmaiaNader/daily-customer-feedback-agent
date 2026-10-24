import pandas as pd

from chat_assistant import answer_question, is_report_request


def sample_frame():
    return pd.DataFrame([
        {"SurveyID": "A1", "SurveyDate": "2026-10-20", "StaffID": "S1001", "StaffName": "Amira Ben Salem",
         "Category": "Baggage", "CustomerName": "Test A", "CustomerComment": "Bag was delayed", "CSATScore": 1},
        {"SurveyID": "A2", "SurveyDate": "2026-10-21", "StaffID": "S1002", "StaffName": "Youssef Trabelsi",
         "Category": "Check-in", "CustomerName": "Test B", "CustomerComment": "Queue was long", "CSATScore": 2},
        {"SurveyID": "A3", "SurveyDate": "2026-10-22", "StaffID": "S1001", "StaffName": "Amira Ben Salem",
         "Category": "Customer Service", "CustomerName": "Test C", "CustomerComment": "Very helpful", "CSATScore": 5},
    ])


def test_answer_count_uses_dataframe_values():
    answer = answer_question(sample_frame(), "How many surveys are there?")
    assert "3" in answer
    assert "2.67/5" in answer


def test_answer_low_score_count_and_comment_listing():
    answer = answer_question(sample_frame(), "Show low score comments")
    assert "2 of 3 surveys" in answer
    assert "Bag was delayed" in answer
    assert "Queue was long" in answer


def test_answer_category_summary_uses_real_counts():
    answer = answer_question(sample_frame(), "Which category has the most complaints?")
    assert "Baggage" in answer
    assert "Check-in" in answer
    assert "1" in answer


def test_answer_specific_staff():
    answer = answer_question(sample_frame(), "What is the CSAT for Amira Ben Salem?")
    assert "Amira Ben Salem" in answer
    assert "2 survey(s)" in answer
    assert "3.00/5" in answer


def test_unknown_question_does_not_invent_an_answer():
    answer = answer_question(sample_frame(), "Which airport caused the delay?")
    assert "couldn't confidently map" in answer


def test_detects_report_request_without_sending_it():
    assert is_report_request("Please prepare a report for this week") == (True, False)
    assert is_report_request("Send the CSAT report to Managers") == (True, True)
    assert is_report_request("What is the average CSAT?") == (False, False)


def test_chat_can_answer_recent_feedback_with_real_comment():
    answer = answer_question(sample_frame(), "Show latest feedback")
    assert "Very helpful" in answer
    assert "2026-10-22" in answer


def test_low_scores_by_category_returns_category_breakdown():
    answer = answer_question(sample_frame(), "Which category has most low scores?")
    assert "tied across" in answer
    assert "Baggage" in answer
    assert "low_scores" in answer


def test_low_scores_by_staff_returns_staff_breakdown():
    answer = answer_question(sample_frame(), "Which staff has most low scores?")
    assert "Amira Ben Salem" in answer
    assert "low_scores" in answer


def test_decline_question_uses_llm_instead_of_only_kpi_fallback(monkeypatch):
    import chat_assistant

    def fake_call(df, question, model=None, deterministic_evidence=None):
        assert question == "Why did CSAT decline in this period?"
        assert len(df) == 3
        return ("**Gemma AI interpretation — local Ollama**\n\nRecurring likely issue: long waits and baggage handling; validate against operations.", None)

    monkeypatch.setattr(chat_assistant, "_call_local_ollama", fake_call)
    answer = answer_question(sample_frame(), "Why did CSAT decline in this period?", model="gemma3:4b", use_llm=True)
    assert "Gemma AI interpretation" in answer
    assert "long waits" in answer


def test_failed_ai_interpretation_is_labelled_python_only(monkeypatch):
    import chat_assistant

    monkeypatch.setattr(chat_assistant, "_call_local_ollama", lambda *args, **kwargs: (None, "Ollama unavailable"))
    answer = answer_question(sample_frame(), "Why did CSAT decline in this period?", model="gemma3:4b", use_llm=True)
    assert "Gemma AI analysis not completed" in answer
    assert "Python-only" in answer
    assert "Ollama unavailable" in answer


def test_force_llm_uses_ai_columns_table(monkeypatch):
    import chat_assistant
    df = sample_frame().copy()
    df["AI_Category"] = ["Baggage", "Check-in & Boarding", "Customer Service & Staff Communication"]
    df["primary_issue"] = ["Delayed bag", "Long queue", "Helpful agent"]
    df["secondary_issue"] = ["None", "None", "None"]
    df["sentiment"] = ["Negative", "Negative", "Positive"]
    df["root_cause_hypothesis"] = ["Handling delay", "Staffing demand", "None"]
    df["recommended_action"] = ["Review baggage timeline", "Review queue capacity", "Maintain good service"]
    seen = {}

    def fake_call(frame, question, model=None, deterministic_evidence=None):
        seen["columns"] = set(frame.columns)
        seen["question"] = question
        return ("**Gemma AI interpretation — local Ollama**\n\nTest result.", None)

    monkeypatch.setattr(chat_assistant, "_call_local_ollama", fake_call)
    answer = answer_question(df, "Analyze this AI-enriched table", model="gemma3:4b", use_llm=True, force_llm=True)
    assert "AI_Category" in seen["columns"]
    assert "primary_issue" in seen["columns"]
    assert "recommended_action" in seen["columns"]
    assert "Gemma AI interpretation" in answer


def test_local_ollama_prompt_includes_ai_enriched_fields(monkeypatch):
    import chat_assistant

    df = sample_frame().copy()
    df["AI_Category"] = ["Baggage", "Check-in & Boarding", "Customer Service & Staff Communication"]
    df["primary_issue"] = ["Delayed bag", "Long queue", "Helpful agent"]
    df["secondary_issue"] = ["Not stated", "Not stated", "Not stated"]
    df["sentiment"] = ["Negative", "Negative", "Positive"]
    df["root_cause_hypothesis"] = ["Handling delay", "Queue capacity", "Not applicable"]
    df["recommended_action"] = ["Review bag timeline", "Review queue capacity", "Maintain practice"]
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"response": "Drivers: baggage delay and long check-in queues. Validate causes with timestamps."}

    monkeypatch.setattr(chat_assistant, "OLLAMA_URL", "http://localhost:11434")
    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["body"] = json
        captured["timeout"] = timeout
        return FakeResponse()
    monkeypatch.setattr(chat_assistant.requests, "post", fake_post)

    answer, error = chat_assistant._call_local_ollama(df, "Why is CSAT low?", model="gemma3:4b")
    assert error is None
    assert "Gemma AI interpretation" in answer
    prompt = captured["body"]["prompt"]
    for field in ["AI_Category", "primary_issue", "sentiment", "root_cause_hypothesis", "recommended_action"]:
        assert field in prompt
    assert "Do not just repeat KPI totals" in prompt
    assert captured["timeout"] == (10, 180)
    assert captured["body"]["options"]["num_ctx"] == 4096
    assert captured["body"]["options"]["num_predict"] == 600
    assert captured["body"]["keep_alive"] == "10m"
