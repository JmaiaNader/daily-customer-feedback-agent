import pytest
from feedback_service import load_recipient_lists_from_sheet, save_recipient_lists_to_sheet
from scheduler_service import _normalise_emails, _validate_recipient_list


URL = "https://docs.google.com/spreadsheets/d/private-list-book/edit"


class FakeRequest:
    def __init__(self, callback):
        self.callback = callback

    def execute(self):
        return self.callback()


class FakeValues:
    def __init__(self, store):
        self.store = store

    def get(self, spreadsheetId, range, **kwargs):
        tab = range.split("!", 1)[0].strip("'")
        return FakeRequest(lambda: {"values": [r[:] for r in self.store.values.get(tab, [])]})

    def clear(self, spreadsheetId, range, body):
        tab = range.split("!", 1)[0].strip("'")
        def clear_values():
            self.store.values[tab] = []
            return {"clearedRange": range}
        return FakeRequest(clear_values)

    def update(self, spreadsheetId, range, valueInputOption, body):
        tab = range.split("!", 1)[0].strip("'")
        def update_values():
            self.store.values[tab] = [row[:] for row in body["values"]]
            return {"updatedRange": range, "updatedRows": len(body["values"])}
        return FakeRequest(update_values)


class FakeSpreadsheets:
    def __init__(self, store):
        self.store = store

    def get(self, spreadsheetId, fields):
        return FakeRequest(lambda: {"sheets": [{"properties": {"title": title}} for title in self.store.titles]})

    def batchUpdate(self, spreadsheetId, body):
        def add_sheets():
            for request in body["requests"]:
                title = request["addSheet"]["properties"]["title"]
                if title not in self.store.titles:
                    self.store.titles.append(title)
                    self.store.values[title] = []
            return {"replies": [{}]}
        return FakeRequest(add_sheets)

    def values(self):
        return FakeValues(self.store)


class FakeService:
    def __init__(self):
        self.titles = ["Sheet1"]
        self.values = {"Sheet1": []}

    def spreadsheets(self):
        return FakeSpreadsheets(self)


def test_recipient_validation_accepts_comma_and_newline_and_deduplicates_case_insensitive():
    name, emails = _validate_recipient_list("Operations", "a@example.com\nB@example.com, A@example.com")
    assert name == "Operations"
    assert emails == ["a@example.com", "B@example.com"]
    assert _normalise_emails(["a@example.com", "A@example.com"]) == ["a@example.com"]


def test_recipient_validation_rejects_missing_name_or_no_valid_emails():
    with pytest.raises(ValueError, match="name"):
        _validate_recipient_list("", "a@example.com")
    with pytest.raises(ValueError, match="valid email"):
        _validate_recipient_list("Managers", "not-an-email")


def test_recipient_lists_save_to_and_load_from_separate_sheet():
    from feedback_service import RECIPIENTS_SHEET_NAME
    service = FakeService()
    lists = {
        "Operations": ["ops@example.com", "ops2@example.com"],
        "Managers": ["manager@example.com"],
    }
    save_recipient_lists_to_sheet(lists, service=service, spreadsheet_url=URL, sheet_name="recipient_lists")
    loaded = load_recipient_lists_from_sheet(service=service, spreadsheet_url=URL, sheet_name="recipient_lists")
    assert loaded == lists
    assert "recipient_lists" in service.titles
    assert service.values["recipient_lists"][0] == ["ListName", "Email"]
    assert RECIPIENTS_SHEET_NAME == "recipient_lists"
