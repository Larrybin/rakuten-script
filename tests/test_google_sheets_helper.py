from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from lib import google_sheets_helper as helper
from lib.errors import ConfigError, SheetsApiError


class DummyHttpResponse:
    status = 403
    reason = "Forbidden"


def test_get_sheets_service_caches(monkeypatch, tmp_path):
    helper._SERVICE = None
    json_file = tmp_path / "sa.json"
    json_file.write_text("{}", encoding="utf-8")

    credential_calls = []
    build_calls = []

    monkeypatch.setattr(helper, "get_google_service_account_file", lambda: json_file)

    class DummyCredentials:
        @staticmethod
        def from_service_account_file(path, scopes):
            credential_calls.append((path, tuple(scopes)))
            return "creds"

    def fake_build(name, version, credentials, cache_discovery):
        build_calls.append((name, version, credentials, cache_discovery))
        return "service"

    monkeypatch.setattr(helper, "Credentials", DummyCredentials)
    monkeypatch.setattr(helper, "build", fake_build)

    first = helper.get_sheets_service()
    second = helper.get_sheets_service()

    assert first == "service"
    assert second == "service"
    assert len(credential_calls) == 1
    assert len(build_calls) == 1


def test_get_sheets_service_file_not_found(monkeypatch):
    helper._SERVICE = None
    missing = "/tmp/not-exist-sa.json"
    monkeypatch.setattr(helper, "get_google_service_account_file", lambda: missing)

    class DummyCredentials:
        @staticmethod
        def from_service_account_file(path, scopes):
            raise FileNotFoundError(path)

    monkeypatch.setattr(helper, "Credentials", DummyCredentials)

    with pytest.raises(ConfigError):
        helper.get_sheets_service()


def test_read_sheet_data_returns_empty(monkeypatch):
    execute = MagicMock(return_value={})
    get = MagicMock(return_value=MagicMock(execute=execute))
    values = MagicMock(return_value=MagicMock(get=get))
    spreadsheets = MagicMock(return_value=MagicMock(values=values))
    service = MagicMock(spreadsheets=spreadsheets)

    rows = helper.read_sheet_data("sheet", "A1:A2", service_obj=service)
    assert rows == []


def test_read_sheet_data_retries_transient_connection_error(monkeypatch):
    attempts = []
    sleep_calls = []

    def execute():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionResetError("Connection reset by peer")
        return {"values": [["ok"]]}

    get = MagicMock(return_value=MagicMock(execute=execute))
    values = MagicMock(return_value=MagicMock(get=get))
    spreadsheets = MagicMock(return_value=MagicMock(values=values))
    service = MagicMock(spreadsheets=spreadsheets)
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    rows = helper.read_sheet_data("sheet", "A1:A2", service_obj=service)

    assert rows == [["ok"]]
    assert len(attempts) == 2
    assert sleep_calls == [1]


def test_write_sheet_data_http_error_raises():
    error = HttpError(resp=DummyHttpResponse(), content=b"forbidden")
    execute = MagicMock(side_effect=error)
    update = MagicMock(return_value=MagicMock(execute=execute))
    values = MagicMock(return_value=MagicMock(update=update))
    spreadsheets = MagicMock(return_value=MagicMock(values=values))
    service = MagicMock(spreadsheets=spreadsheets)

    with pytest.raises(SheetsApiError):
        helper.write_sheet_data([["1"]], "sheet", "A1", service_obj=service)


def test_append_rows_to_sheet_calls_insert_rows():
    execute = MagicMock(return_value={"updates": {"updatedRows": 1}})
    append = MagicMock(return_value=MagicMock(execute=execute))
    values = MagicMock(return_value=MagicMock(append=append))
    spreadsheets = MagicMock(return_value=MagicMock(values=values))
    service = MagicMock(spreadsheets=spreadsheets)

    helper.append_rows_to_sheet([["1", "2"]], "sheet", "Sheet1", service_obj=service)

    kwargs = append.call_args.kwargs
    assert kwargs["spreadsheetId"] == "sheet"
    assert kwargs["range"] == "Sheet1"
    assert kwargs["valueInputOption"] == "RAW"
    assert kwargs["insertDataOption"] == "INSERT_ROWS"


def test_append_rows_to_sheet_retries_transient_connection_error(monkeypatch):
    attempts = []
    sleep_calls = []

    def execute():
        attempts.append(1)
        if len(attempts) <= 2:
            raise ConnectionResetError("Connection reset by peer")
        return {"updates": {"updatedRows": 1}}

    append = MagicMock(return_value=MagicMock(execute=execute))
    values = MagicMock(return_value=MagicMock(append=append))
    spreadsheets = MagicMock(return_value=MagicMock(values=values))
    service = MagicMock(spreadsheets=spreadsheets)
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    helper.append_rows_to_sheet([["1", "2"]], "sheet", "Sheet1", service_obj=service)

    assert len(attempts) == 3
    assert len(sleep_calls) == 2
