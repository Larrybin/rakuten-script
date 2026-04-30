from scripts import sync_master_to_runtime


def test_task_source_specs_requires_category_mapping():
    class DummySubject:
        env_serial = "3"

    active_subjects = {"a@test.com": DummySubject()}
    task_rows = [
        sync_master_to_runtime.TaskSourceRow(
            row_index=2,
            subject_id="a@test.com",
            rakuten_account="a@test.com",
            task_type="category",
            task_value="Fashion",
            status="active",
            note="",
        )
    ]
    errors = []

    specs = sync_master_to_runtime._task_source_specs(active_subjects, task_rows, {}, errors)

    assert specs == []
    assert errors == ["category_map 缺少分类映射: Fashion"]


def test_task_source_specs_builds_keyword_row():
    class DummySubject:
        env_serial = "3"

    active_subjects = {"a@test.com": DummySubject()}
    task_rows = [
        sync_master_to_runtime.TaskSourceRow(
            row_index=2,
            subject_id="a@test.com",
            rakuten_account="a@test.com",
            task_type="keyword",
            task_value="Shoes",
            status="active",
            note="",
        )
    ]
    errors = []

    specs = sync_master_to_runtime._task_source_specs(active_subjects, task_rows, {}, errors)

    assert len(specs) == 1
    assert specs[0].sheet_name == sync_master_to_runtime.KEYWORDS_SHEET
    assert specs[0].row_payload["subject_id"] == "a@test.com"
    assert specs[0].row_payload["env_serial"] == "3"
