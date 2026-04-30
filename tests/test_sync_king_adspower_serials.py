from scripts.sync_king_adspower_serials import find_serial_update_plan


def test_find_serial_update_plan_matches_by_name():
    king_rows = [
        {
            "row_index": 2,
            "指纹id": "Z117",
            "乐天账号": "a@test.com",
            "乐天密码": "secret",
            "乐天状态": "active",
        }
    ]
    profiles = [
        {"profile_id": "pid-1", "serial_number": "289", "name": "Z117"},
    ]

    updates, errors = find_serial_update_plan(king_rows, profiles)

    assert errors == []
    assert updates == [{"row_index": 2, "old_value": "Z117", "new_value": "289", "match_type": "name"}]


def test_find_serial_update_plan_skips_existing_serial_number():
    king_rows = [
        {
            "row_index": 2,
            "指纹id": "306",
            "乐天账号": "a@test.com",
            "乐天密码": "secret",
            "乐天状态": "active",
        }
    ]
    profiles = [
        {"profile_id": "pid-1", "serial_number": "306", "name": "Z118"},
    ]

    updates, errors = find_serial_update_plan(king_rows, profiles)

    assert updates == []
    assert errors == []


def test_find_serial_update_plan_reports_ambiguous_name():
    king_rows = [
        {
            "row_index": 2,
            "指纹id": "Z117",
            "乐天账号": "a@test.com",
            "乐天密码": "secret",
            "乐天状态": "active",
        }
    ]
    profiles = [
        {"profile_id": "pid-1", "serial_number": "289", "name": "Z117"},
        {"profile_id": "pid-2", "serial_number": "290", "name": "Z117"},
    ]

    updates, errors = find_serial_update_plan(king_rows, profiles)

    assert updates == []
    assert errors == ["King 第 2 行指纹id值无法唯一匹配 AdsPower profile: Z117"]
