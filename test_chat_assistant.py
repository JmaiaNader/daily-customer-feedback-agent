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
