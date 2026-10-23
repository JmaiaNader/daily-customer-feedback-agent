from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from feedback_service import (
    STAFF_LIST,
    build_submission_record,
    classify_feedback,
    next_staff,
    spreadsheet_id_from_url,
    validate_submission,
)


def test_validate_submission_trims_text_and_parses_score():
    result = validate_submission("  Dana  ", "  The queue was too long.  ", "2")
    assert result == {
        "CustomerName": "Dana",
        "CustomerComment": "The queue was too long.",
        "CSATScore": 2,
    }


@pytest.mark.parametrize(
    "name,feedback,score",
    [("", "Okay", 3), ("Dana", "", 3), ("Dana", "Good", 0), ("Dana", "Good", 6), ("Dana", "Good", 2.5)],
)
def test_validate_submission_rejects_invalid_inputs(name, feedback, score):
    with pytest.raises(ValueError):
        validate_submission(name, feedback, score)


def test_staff_assignment_round_robin_and_unknown_previous_staff():
    assert next_staff("S1001")["StaffID"] == "S1002"
    assert next_staff("S1002")["StaffID"] == "S1003"
    assert next_staff("S1003")["StaffID"] == "S1001"
    assert next_staff("S1008")["StaffID"] == "S1001"


def test_category_rules_use_existing_categories():
    assert classify_feedback("My baggage was delayed") == "Baggage"
    assert classify_feedback("The check-in queue was long") == "Check-in"
    assert classify_feedback("The agent gave me an unclear answer") == "Customer Service"


def test_build_submission_record_includes_backend_fields_and_channel():
    fixed_time = datetime(2026, 10, 23, 12, 30, tzinfo=ZoneInfo("Asia/Qatar"))
    record = build_submission_record("Dana", "My bag arrived late", 1, STAFF_LIST[2], now=fixed_time)
    assert record["SurveyID"].startswith("FB-20261023123000-")
    assert record["SurveyDate"] == "2026-10-23"
    assert "T" not in record["SurveyDate"]
    assert record["StaffID"] == "S1003"
    assert record["StaffName"] == "Sami Haddad"
    assert record["Category"] == "Baggage"
    assert record["CustomerName"] == "Dana"
    assert record["CSATScore"] == 1
    assert record["Channel"] == "Workshop Feedback Form"
    assert record["FlightNumber"] == "AB101"
    assert record["Airport"] == "DOH"


def test_extracts_spreadsheet_id():
    assert spreadsheet_id_from_url("https://docs.google.com/spreadsheets/d/abc_DEF-123/edit?gid=1") == "abc_DEF-123"




def test_next_flight_details_rotates_through_existing_pairs():
    from feedback_service import next_flight_details

    headers = ["SurveyID", "SurveyDate", "FlightNumber", "Airport"]
    rows = [
        headers,
        ["SV1", "2026-10-20", "AB101", "DOH"],
        ["SV2", "2026-10-21", "AB102", "DOH"],
    ]
    assert next_flight_details(headers, rows) == {"FlightNumber": "AB101", "Airport": "DOH"}


def test_flight_rotation_handles_customer_name_header_added_during_submission():
    from feedback_service import next_flight_details

    # The Google Sheet's raw header doesn't yet contain CustomerName, but the
    # backend has already added that header to its in-memory schema.
    original_headers = ["SurveyID", "SurveyDate", "FlightNumber", "Airport"]
    current_headers = original_headers + ["CustomerName"]
    rows = [
        original_headers,
        ["SV1", "2026-10-20", "AB101", "DOH"],
        ["SV2", "2026-10-21", "AB102", "DOH"],
    ]
    assert next_flight_details(current_headers, rows) == {"FlightNumber": "AB101", "Airport": "DOH"}


def test_invalid_spreadsheet_url_raises():
    with pytest.raises(RuntimeError, match="Google Sheets spreadsheet URL"):
        spreadsheet_id_from_url("https://drive.google.com/file/d/abc/view")

class _FakeRequest:
    def __init__(self, callback):
        self.callback = callback

    def execute(self):
        return self.callback()


class _FakeValuesResource:
    def __init__(self, owner):
        self.owner = owner

    def get(self, spreadsheetId, range):
        return _FakeRequest(lambda: {"values": [row[:] for row in self.owner.rows]})

    def update(self, spreadsheetId, range, valueInputOption, body):
        def do_update():
            # The backend only updates a single header cell here; convert e.g. I1.
            cell = range.rsplit("!", 1)[-1]
            col_letters = "".join(ch for ch in cell if ch.isalpha())
            row_num = int("".join(ch for ch in cell if ch.isdigit()))
            col_num = 0
            for ch in col_letters:
                col_num = col_num * 26 + ord(ch.upper()) - 64
            while len(self.owner.rows) < row_num:
                self.owner.rows.append([])
            row = self.owner.rows[row_num - 1]
            while len(row) < col_num:
                row.append("")
            row[col_num - 1] = body["values"][0][0]
            return {"updatedRange": range}
        return _FakeRequest(do_update)

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        def do_append():
            self.owner.rows.extend([row[:] for row in body["values"]])
            return {"updates": {"updatedRows": len(body["values"])}}
        return _FakeRequest(do_append)


class _FakeSpreadsheetsResource:
    def __init__(self, owner):
        self.owner = owner

    def values(self):
        return _FakeValuesResource(self.owner)


class _FakeSheetsService:
    def __init__(self, rows):
        self.rows = [row[:] for row in rows]

    def spreadsheets(self):
        return _FakeSpreadsheetsResource(self)


def test_submit_feedback_appends_row_and_auto_assigns_next_staff():
    from feedback_service import submit_feedback

    # CustomerName is intentionally missing to test automatic header migration.
    headers = ["SurveyID", "SurveyDate", "StaffID", "StaffName", "Category",
               "CustomerComment", "CSATScore", "Channel"]
    old_row = ["SV100", "2026-10-22", "S1001", "Amira Ben Salem", "Customer Service",
               "Previous comment", "4", "Web"]
    fake = _FakeSheetsService([headers, old_row])

    result = submit_feedback(
        "Test Participant", "My baggage was delayed", 2,
        service=fake,
        spreadsheet_url="https://docs.google.com/spreadsheets/d/test_sheet_id/edit",
        sheet_name="rowdata",
    )

    assert result["success"] is True
    assert result["staff_id"] == "S1002"
    assert "CustomerName" in fake.rows[0]
    assert "FlightNumber" in fake.rows[0]
    assert "Airport" in fake.rows[0]
    new_row = fake.rows[-1]
    row_by_header = dict(zip(fake.rows[0], new_row))
    assert row_by_header["CustomerName"] == "Test Participant"
    assert row_by_header["CustomerComment"] == "My baggage was delayed"
    assert row_by_header["CSATScore"] == 2
    assert row_by_header["Category"] == "Baggage"
    assert row_by_header["StaffName"] == "Youssef Trabelsi"
    assert row_by_header["Channel"] == "Workshop Feedback Form"
    assert row_by_header["SurveyDate"][:10] == row_by_header["SurveyDate"]
    assert row_by_header["FlightNumber"]
    assert row_by_header["Airport"]
    assert row_by_header["SurveyID"].startswith("FB-")
