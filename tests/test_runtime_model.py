from lib.runtime_model import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_BLOCKED,
    PARTNERSHIP_DEEPLINKS_HEADERS,
    PARTNERSHIP_DEEPLINKS_SHEET,
    TASK_SHEETS,
    TaskSourceRow,
    index_active_subjects,
    normalize_account_status,
    normalize_subject_id,
    parse_king_rows,
)


def test_normalize_subject_id():
    assert normalize_subject_id("  Foo@Bar.com ") == "foo@bar.com"


def test_normalize_account_status_accepts_operational_aliases():
    assert normalize_account_status("活着") == ACCOUNT_STATUS_ACTIVE
    assert normalize_account_status("需要人脸验证") == ACCOUNT_STATUS_BLOCKED
    assert normalize_account_status("乐天账号要改媒体，之前的ins挂了") == ACCOUNT_STATUS_BLOCKED


def test_index_active_subjects_detects_duplicates():
    rows = [
        type("Row", (), {"subject_id": "a@test.com", "account_status": ACCOUNT_STATUS_ACTIVE, "rakuten_account": "a@test.com"})(),
        type("Row", (), {"subject_id": "a@test.com", "account_status": ACCOUNT_STATUS_ACTIVE, "rakuten_account": "a@test.com"})(),
    ]
    active, errors = index_active_subjects(rows)
    assert active == {}
    assert errors == ["King 存在重复 active 乐天账号: a@test.com"]


def test_parse_king_rows_skips_rows_without_rakuten_account(monkeypatch):
    def fake_read_sheet_with_headers(spreadsheet_id, sheet_name, service):
        return (
            [
                "指纹id",
                "乐天账号",
                "乐天密码",
                "乐天状态",
                "类型",
                "RAKUTEN_ACCOUNT_ID",
                "RAKUTEN_CLIENT_ID",
                "RAKUTEN_CLIENT_SECRET",
            ],
            [
                ["3", "", "", "", "男装", "", "", ""],
                ["4", "vc.ddom@outlook.com", "secret", "active", "女装", "account-id", "client-id", "client-secret"],
            ],
        )

    monkeypatch.setattr("lib.runtime_model.read_sheet_with_headers", fake_read_sheet_with_headers)

    rows, errors = parse_king_rows("sheet-id", object())

    assert errors == []
    assert len(rows) == 1
    assert rows[0].subject_id == "vc.ddom@outlook.com"
    assert rows[0].rakuten_account_id == "account-id"
    assert rows[0].rakuten_client_id == "client-id"
    assert rows[0].rakuten_client_secret == "client-secret"


def test_partnership_deeplinks_sheet_is_in_runtime_layout():
    assert TASK_SHEETS[PARTNERSHIP_DEEPLINKS_SHEET] == PARTNERSHIP_DEEPLINKS_HEADERS
    assert PARTNERSHIP_DEEPLINKS_HEADERS[
        PARTNERSHIP_DEEPLINKS_HEADERS.index("advertiser_url") + 1
    ] == "ships_to"
