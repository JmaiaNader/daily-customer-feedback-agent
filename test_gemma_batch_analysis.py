import json

import gemma_batch_analysis as gba


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return {"response": json.dumps(self.payload)}


def test_batch_request_maps_results_by_row_id_and_uses_json_mode(monkeypatch):
    captured = {}
    payload = {"results": [
        {"row_id": 8, "primary_issue": "Refund delay", "secondary_issue": "None", "sentiment": "Negative",
         "root_cause_hypothesis": "Possible process delay", "recommended_action": "Review refund SLA", "AI_Category": "Refunds"},
        {"row_id": 3, "primary_issue": "Baggage delay", "secondary_issue": "No updates", "sentiment": "Negative",
         "root_cause_hypothesis": "Possible handoff issue", "recommended_action": "Review baggage tracking", "AI_Category": "Baggage"},
    ]}

    def fake_post(url, json, timeout):
        captured.update(url=url, body=json, timeout=timeout)
        return FakeResponse(payload)

    monkeypatch.setattr(gba.requests, "post", fake_post)
    categories = ["Refunds", "Baggage", "Other / Unclear"]
    records = [
        {"row_id": 8, "comment": "Refund is late", "csat_score": "1", "original_category": "Refund"},
        {"row_id": 3, "comment": "Bag arrived late", "csat_score": "2", "original_category": "Baggage"},
    ]

    result = gba.analyze_feedback_batch(records, model="gemma3:4b", ollama_url="http://localhost:11434", categories=categories)

    assert set(result) == {3, 8}
    assert result[8]["AI_Category"] == "Refunds"
    assert result[3]["AI_Category"] == "Baggage"
    assert captured["url"].endswith("/api/generate")
    assert captured["body"]["format"] == "json"
    assert captured["body"]["keep_alive"] == "10m"
    assert "row_id" in captured["body"]["prompt"]


def test_unrecognized_category_is_normalized(monkeypatch):
    payload = {"results": [{
        "row_id": 0, "primary_issue": "Issue", "secondary_issue": "Not stated", "sentiment": "Unknown",
        "root_cause_hypothesis": "Possible issue", "recommended_action": "Review", "AI_Category": "Made Up Category"
    }]}
    monkeypatch.setattr(gba.requests, "post", lambda *a, **k: FakeResponse(payload))
    result = gba.analyze_feedback_batch(
        [{"row_id": 0, "comment": "Problem", "csat_score": "1", "original_category": ""}],
        model="gemma3:4b", ollama_url="http://localhost:11434", categories=["Refunds", "Other / Unclear"]
    )
    assert result[0]["AI_Category"] == "Other / Unclear"
    assert result[0]["sentiment"] == "Neutral"


def test_empty_batch_does_not_call_ollama(monkeypatch):
    monkeypatch.setattr(gba.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call")))
    assert gba.analyze_feedback_batch([], model="gemma3:4b", ollama_url="http://localhost:11434", categories=[]) == {}
