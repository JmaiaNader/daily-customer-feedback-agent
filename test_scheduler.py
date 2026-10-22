from datetime import date
import pandas as pd
import pytest
import scheduler_service as scheduler


def test_resolve_yesterday_uses_scheduler_timezone(monkeypatch):
    class FakeDateTime:
        @staticmethod
        def now(tz):
            from datetime import datetime
            return datetime(2026, 10, 22, 9, 0, tzinfo=tz)
    monkeypatch.setattr(scheduler, "datetime", FakeDateTime)
    df = pd.DataFrame({"SurveyDate": [date(2026, 10, 21), date(2026, 10, 22)]})
    assert scheduler._resolve_dates({"date_mode": "yesterday"}, df) == (date(2026, 10, 21), date(2026, 10, 21))


def test_resolve_latest_available_day_uses_max_date():
    df = pd.DataFrame({"SurveyDate": [date(2026, 10, 19), date(2026, 10, 21)]})
    assert scheduler._resolve_dates({"date_mode": "latest available day"}, df) == (date(2026, 10, 21), date(2026, 10, 21))


def test_resolve_custom_range_rejects_reversed_dates():
    df = pd.DataFrame({"SurveyDate": [date(2026, 10, 19)]})
    with pytest.raises(ValueError, match="on or before"):
        scheduler._resolve_dates({"date_mode": "custom range", "custom_start": "2026-10-22", "custom_end": "2026-10-19"}, df)


def test_resolve_dates_rejects_empty_source():
    with pytest.raises(ValueError, match="no valid SurveyDate"):
        scheduler._resolve_dates({"date_mode": "latest available day"}, pd.DataFrame({"SurveyDate": []}))


def test_recipient_list_normalization():
    assert scheduler._normalise_emails("a@example.com; b@example.com, a@example.com") == ["a@example.com", "b@example.com"]
