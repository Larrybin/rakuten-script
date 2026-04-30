import rakuten_aff_offer


def test_append_branlist_records_batches_rows(monkeypatch):
    calls = []

    monkeypatch.setattr(rakuten_aff_offer, "get_spreadsheet_id", lambda: "sheet-id")
    monkeypatch.setattr(
        rakuten_aff_offer,
        "append_rows_to_sheet",
        lambda rows, spreadsheet_id, sheet_name, service_obj=None: calls.append(
            (rows, spreadsheet_id, sheet_name, service_obj)
        ),
    )

    records = [
        {header: f"{header}-1" for header in rakuten_aff_offer.BRANLIST_HEADERS},
        {header: f"{header}-2" for header in rakuten_aff_offer.BRANLIST_HEADERS},
    ]

    rakuten_aff_offer.append_branlist_records(records, service="svc")

    assert len(calls) == 1
    rows, spreadsheet_id, sheet_name, service = calls[0]
    assert spreadsheet_id == "sheet-id"
    assert sheet_name == rakuten_aff_offer.BRANLIST_SHEET
    assert service == "svc"
    assert rows == [
        [f"{header}-1" for header in rakuten_aff_offer.BRANLIST_HEADERS],
        [f"{header}-2" for header in rakuten_aff_offer.BRANLIST_HEADERS],
    ]


def test_append_branlist_records_chunks_large_batches(monkeypatch):
    calls = []

    monkeypatch.setattr(rakuten_aff_offer, "get_spreadsheet_id", lambda: "sheet-id")
    monkeypatch.setattr(rakuten_aff_offer.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        rakuten_aff_offer,
        "append_rows_to_sheet",
        lambda rows, spreadsheet_id, sheet_name, service_obj=None: calls.append(rows),
    )

    records = [
        {header: f"{header}-{idx}" for header in rakuten_aff_offer.BRANLIST_HEADERS}
        for idx in range(205)
    ]

    rakuten_aff_offer.append_branlist_records(records, service="svc")

    assert [len(batch) for batch in calls] == [100, 100, 5]


def test_load_all_brands_stops_when_count_stays_stale(monkeypatch):
    clicks = []
    counts = iter([[{"brand": "A"}], [{"brand": "A"}], [{"brand": "A"}]])

    monkeypatch.setattr(rakuten_aff_offer, "extract_brand_records", lambda driver: next(counts))
    monkeypatch.setattr(rakuten_aff_offer, "_find_el_clickable", lambda driver, by, loc, timeout=5: object())
    monkeypatch.setattr(rakuten_aff_offer, "_click_el", lambda driver, el: clicks.append(el) or True)
    monkeypatch.setattr(rakuten_aff_offer.time, "sleep", lambda seconds: None)

    class Driver:
        def execute_script(self, script, element):
            return None

    rakuten_aff_offer.load_all_brands(Driver(), max_clicks=10, stale_limit=2)

    assert len(clicks) == 2


def test_wait_for_search_results_ready_waits_until_cards_exist(monkeypatch):
    counts = iter([0, 0, 213])
    card_states = iter([False, False, True])

    monkeypatch.setattr(rakuten_aff_offer, "get_total_brand_count", lambda driver: next(counts))
    monkeypatch.setattr(rakuten_aff_offer, "has_search_result_cards", lambda driver: next(card_states))
    monkeypatch.setattr(rakuten_aff_offer, "has_no_search_results", lambda driver: False)
    monkeypatch.setattr(rakuten_aff_offer.time, "sleep", lambda seconds: None)

    state, total = rakuten_aff_offer.wait_for_search_results_ready(object(), timeout=5)

    assert state == "results"
    assert total == 213


def test_wait_for_search_results_ready_returns_empty_when_no_results_message_seen(monkeypatch):
    monkeypatch.setattr(rakuten_aff_offer, "get_total_brand_count", lambda driver: 0)
    monkeypatch.setattr(rakuten_aff_offer, "has_search_result_cards", lambda driver: False)
    checks = {"count": 0}

    def fake_no_results(driver):
        checks["count"] += 1
        return checks["count"] >= 2

    monkeypatch.setattr(rakuten_aff_offer, "has_no_search_results", fake_no_results)
    monkeypatch.setattr(rakuten_aff_offer.time, "sleep", lambda seconds: None)

    state, total = rakuten_aff_offer.wait_for_search_results_ready(object(), timeout=5)

    assert state == "empty"
    assert total == 0
