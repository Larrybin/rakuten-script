from scripts import init_sheet_layout


def test_init_sheet_layout_uses_env_spreadsheet_id(monkeypatch):
    monkeypatch.setattr(init_sheet_layout, "get_google_spreadsheet_id", lambda: "sheet-id")
    monkeypatch.setattr(init_sheet_layout, "get_sheets_service", lambda: "service")
    ensure_calls = []
    monkeypatch.setattr(
        init_sheet_layout,
        "ensure_runtime_sheets",
        lambda spreadsheet_id, service: ensure_calls.append(("runtime", spreadsheet_id, service)) or ["task_source"],
    )
    monkeypatch.setattr(
        init_sheet_layout,
        "ensure_king_status_column",
        lambda spreadsheet_id, service: ensure_calls.append(("king", spreadsheet_id, service)) or True,
    )

    class DummyArgs:
        spreadsheet_id = None

    monkeypatch.setattr(init_sheet_layout.argparse.ArgumentParser, "parse_args", lambda self: DummyArgs())

    init_sheet_layout.main()

    assert ensure_calls == [
        ("runtime", "sheet-id", "service"),
        ("king", "sheet-id", "service"),
    ]
