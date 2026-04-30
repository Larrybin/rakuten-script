import rakuten_aff_apply


def test_read_apply_windows_uses_apply_window_sheet(monkeypatch):
    calls = []

    def fake_read_sheet_with_headers(spreadsheet_id, sheet_name, service):
        calls.append((spreadsheet_id, sheet_name, service))
        return (
            rakuten_aff_apply.APPLY_WINDOW_HEADERS,
            [["subject@test.com", "6", "2026-04-21T00:00:00+08:00", "2026-04-22T00:00:00+08:00", "34", "active"]],
        )

    monkeypatch.setattr(rakuten_aff_apply, "get_spreadsheet_id", lambda: "sheet-id")
    monkeypatch.setattr(rakuten_aff_apply, "read_sheet_with_headers", fake_read_sheet_with_headers)

    windows, header_map = rakuten_aff_apply.read_apply_windows("svc", "subject@test.com")

    assert calls == [("sheet-id", rakuten_aff_apply.APPLY_WINDOW_SHEET, "svc")]
    assert windows[0]["limit"] == "34"
    assert "subject_id" in header_map
