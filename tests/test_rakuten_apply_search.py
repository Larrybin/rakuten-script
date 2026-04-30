import rakuten_aff_apply


def test_search_brand_navigates_directly_and_does_not_refill_input(monkeypatch):
    calls = []

    class SearchInput:
        def get_attribute(self, name):
            return "COS KR" if name == "value" else ""

        def send_keys(self, value):
            calls.append(("send_keys", value))

    search_input = SearchInput()

    monkeypatch.setattr(
        rakuten_aff_apply,
        "_find_el_clickable",
        lambda driver, by, loc, timeout=10: search_input,
    )
    monkeypatch.setattr(
        rakuten_aff_apply,
        "fill_input_value",
        lambda driver, element, value: calls.append(("unexpected_fill", value)),
    )
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)

    class Driver:
        def get(self, url):
            calls.append(("get", url))

    assert rakuten_aff_apply.search_brand(Driver(), "COS KR") is True
    assert ("get", "https://publisher.rakutenadvertising.com/advertisers/find?query=COS+KR&index=advertisers") in calls
    assert ("unexpected_fill", "COS KR") not in calls


def test_search_brand_fails_when_input_value_does_not_match(monkeypatch):
    class SearchInput:
        def get_attribute(self, name):
            return "" if name == "value" else ""

    monkeypatch.setattr(
        rakuten_aff_apply,
        "_find_el_clickable",
        lambda driver, by, loc, timeout=10: SearchInput() if "input" in loc else object(),
    )
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)

    class Driver:
        def get(self, url):
            return None

    assert rakuten_aff_apply.search_brand(Driver(), "COS KR") is False


def test_search_brand_removes_ampersand_from_query(monkeypatch):
    calls = []

    class SearchInput:
        def get_attribute(self, name):
            return "Johnston Murphy" if name == "value" else ""

    monkeypatch.setattr(
        rakuten_aff_apply,
        "_find_el_clickable",
        lambda driver, by, loc, timeout=10: SearchInput(),
    )
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)

    class Driver:
        def get(self, url):
            calls.append(("get", url))

    assert rakuten_aff_apply.search_brand(Driver(), "Johnston & Murphy") is True
    assert (
        "get",
        "https://publisher.rakutenadvertising.com/advertisers/find?query=Johnston+Murphy&index=advertisers",
    ) in calls


def test_find_offer_apply_button_falls_back_to_presence_lookup(monkeypatch):
    class Button:
        pass

    button = Button()
    monkeypatch.setattr(rakuten_aff_apply, "_find_el_clickable", lambda driver, by, loc, timeout=2: None)
    monkeypatch.setattr(
        rakuten_aff_apply,
        "_find_el",
        lambda driver, by, loc, timeout=2: button if "Apply" in loc else None,
    )

    assert rakuten_aff_apply.find_offer_apply_button(object()) is button


def test_find_offer_apply_button_uses_js_dom_lookup_first():
    class Button:
        pass

    button = Button()

    class Driver:
        def execute_script(self, script):
            return button

    assert rakuten_aff_apply.find_offer_apply_button(Driver()) is button


def test_process_brand_application_marks_failed_when_search_did_not_execute(monkeypatch):
    updates = []
    brand_info = {"brand": "COS KR", "row_index": 56, "brand_url": ""}

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: False)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []))
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(object(), brand_info, service="svc", header_map={}) is False
    assert updates == [(56, rakuten_aff_apply.APPLY_STATUS_FAILED, "search not executed")]


def test_process_brand_application_marks_failed_when_results_do_not_refresh(monkeypatch):
    updates = []
    brand_info = {"brand": "COS KR", "row_index": 56, "brand_url": ""}

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(
        rakuten_aff_apply,
        "find_exact_match_card",
        lambda driver, brand: (None, ["Fishpools", "Matte Collection", "Modaselle"]),
    )
    monkeypatch.setattr(
        rakuten_aff_apply,
        "wait_for_search_results",
        lambda driver, brand, before_titles: ("stale", None, ["Fishpools", "Matte Collection", "Modaselle"]),
    )
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(object(), brand_info, service="svc", header_map={}) is False
    assert updates == [(56, rakuten_aff_apply.APPLY_STATUS_FAILED, "search results not refreshed")]


def test_process_brand_application_marks_failed_when_results_do_not_load(monkeypatch):
    updates = []
    brand_info = {"brand": "Solid & Striped", "row_index": 62, "brand_url": ""}

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []))
    monkeypatch.setattr(
        rakuten_aff_apply,
        "wait_for_search_results",
        lambda driver, brand, before_titles: ("timeout", None, []),
    )
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(object(), brand_info, service="svc", header_map={}) is False
    assert updates == [(62, rakuten_aff_apply.APPLY_STATUS_FAILED, "search results not loaded")]


def test_process_brand_application_marks_explicit_no_results_as_skipped(monkeypatch):
    updates = []
    brand_info = {"brand": "Johnston & Murphy", "row_index": 6, "brand_url": ""}

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []))
    monkeypatch.setattr(
        rakuten_aff_apply,
        "wait_for_search_results",
        lambda driver, brand, before_titles: ("no_results", None, []),
    )
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(object(), brand_info, service="svc", header_map={}) is False
    assert updates == [(6, rakuten_aff_apply.APPLY_STATUS_SKIPPED, "offer not found")]


def test_process_brand_application_marks_missing_apply_button_as_failed(monkeypatch):
    updates = []
    brand_info = {"brand": "Mack Weldon", "row_index": 5, "brand_url": ""}

    class Button:
        pass

    class Card:
        text = "Mack Weldon Not partnered"

        def find_elements(self, by, loc):
            return []

        def find_element(self, by, loc):
            return Button()

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/advertisers/find?query=Mack+Weldon&index=advertisers"

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []) if not brand else (Card(), ["Mack Weldon"]))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_search_results", lambda driver, brand, before_titles: ("ready", Card(), ["Mack Weldon"]))
    monkeypatch.setattr(rakuten_aff_apply, "_click_el", lambda driver, element: True)
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_offer_apply_button", lambda driver, timeout=30: ("timeout", None))
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(Driver(), brand_info, service="svc", header_map={}) is False
    assert updates == [(5, rakuten_aff_apply.APPLY_STATUS_FAILED, "apply button not found")]


def test_process_brand_application_waits_for_offer_apply_button(monkeypatch):
    clicked = []
    updates = []
    brand_info = {"brand": "Johnston & Murphy", "row_index": 6, "brand_url": ""}

    class Button:
        def get_attribute(self, name):
            return None

    class Card:
        text = "Johnston & Murphy Not partnered"

        def find_elements(self, by, loc):
            return []

        def find_element(self, by, loc):
            return Button()

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/advertisers/38419/offers/123/details"

        def find_elements(self, by, loc):
            return [Button()]

        def refresh(self):
            return None

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []) if not brand else (Card(), ["Johnston & Murphy"]))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_search_results", lambda driver, brand, before_titles: ("ready", Card(), ["Johnston & Murphy"]))
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_offer_apply_button", lambda driver, timeout=30: ("ready", Button()))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_send_request_result", lambda driver, timeout=30: "pending")
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_post_submit_status", lambda driver, timeout=30: "pending")
    monkeypatch.setattr(rakuten_aff_apply, "_find_el", lambda driver, by, loc, timeout=10: object())
    monkeypatch.setattr(
        rakuten_aff_apply,
        "_click_el",
        lambda driver, element: clicked.append(type(element).__name__) or True,
    )
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(Driver(), brand_info, service="svc", header_map={}) is True
    assert clicked[:2] == ["Button", "Button"]
    assert updates == [(6, rakuten_aff_apply.APPLY_STATUS_APPLIED, "Pending (applied)")]


def test_process_brand_application_does_not_refresh_before_send_result(monkeypatch):
    updates = []
    refreshed = []
    brand_info = {"brand": "Stacy Adams", "row_index": 7, "brand_url": ""}

    class Button:
        def get_attribute(self, name):
            return None

    class Card:
        text = "Stacy Adams Not partnered"

        def find_elements(self, by, loc):
            return []

        def find_element(self, by, loc):
            return Button()

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/advertisers/3383/offers/1214430/details"

        def find_elements(self, by, loc):
            return [Button()]

        def refresh(self):
            refreshed.append(True)

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []) if not brand else (Card(), ["Stacy Adams"]))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_search_results", lambda driver, brand, before_titles: ("ready", Card(), ["Stacy Adams"]))
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_offer_apply_button", lambda driver, timeout=30: ("ready", Button()))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_send_request_result", lambda driver, timeout=30: "timeout")
    monkeypatch.setattr(rakuten_aff_apply, "_click_el", lambda driver, element: True)
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(Driver(), brand_info, service="svc", header_map={}) is False
    assert refreshed == []
    assert updates == [(7, rakuten_aff_apply.APPLY_STATUS_FAILED, "send request result not confirmed")]


def test_process_brand_application_records_pending_when_send_button_unavailable(monkeypatch):
    updates = []
    brand_info = {"brand": "Mario Badescu", "row_index": 10, "brand_url": ""}

    class DisabledButton:
        def get_attribute(self, name):
            return "true" if name == "disabled" else None

    class Button:
        pass

    class Card:
        text = "Mario Badescu Not partnered"

        def find_elements(self, by, loc):
            return []

        def find_element(self, by, loc):
            return Button()

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/advertisers/47926/offers/1079446/details"

        def find_elements(self, by, loc):
            return [DisabledButton()]

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []) if not brand else (Card(), ["Mario Badescu"]))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_search_results", lambda driver, brand, before_titles: ("ready", Card(), ["Mario Badescu"]))
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_offer_apply_button", lambda driver, timeout=30: ("ready", Button()))
    monkeypatch.setattr(rakuten_aff_apply, "_click_el", lambda driver, element: True)
    monkeypatch.setattr(rakuten_aff_apply, "record_current_partnership_state", lambda driver, row_idx, header_map, brand_url, service=None: updates.append((row_idx, rakuten_aff_apply.APPLY_STATUS_APPLIED, "Pending (applied)")) or True)

    assert rakuten_aff_apply.process_brand_application(Driver(), brand_info, service="svc", header_map={}) is True
    assert updates == [(10, rakuten_aff_apply.APPLY_STATUS_APPLIED, "Pending (applied)")]


def test_process_brand_application_waits_for_auto_pending_before_refresh(monkeypatch):
    updates = []
    refreshed = []
    brand_info = {"brand": "maurices", "row_index": 11, "brand_url": ""}

    class Button:
        def get_attribute(self, name):
            return None

    class Card:
        text = "maurices Not partnered"

        def find_elements(self, by, loc):
            return []

        def find_element(self, by, loc):
            return Button()

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/advertisers/40158/offers/1786158/details"

        def find_elements(self, by, loc):
            return [Button()]

        def refresh(self):
            refreshed.append(True)

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []) if not brand else (Card(), ["maurices"]))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_search_results", lambda driver, brand, before_titles: ("ready", Card(), ["maurices"]))
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_offer_apply_button", lambda driver, timeout=30: ("ready", Button()))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_send_request_result", lambda driver, timeout=30: "success_message")
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_post_submit_status", lambda driver, timeout=30: "pending")
    monkeypatch.setattr(rakuten_aff_apply, "_find_el", lambda driver, by, loc, timeout=10: object())
    monkeypatch.setattr(rakuten_aff_apply, "_click_el", lambda driver, element: True)
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(Driver(), brand_info, service="svc", header_map={}) is True
    assert refreshed == []
    assert updates == [(11, rakuten_aff_apply.APPLY_STATUS_APPLIED, "Pending (applied)")]


def test_process_brand_application_refreshes_when_auto_pending_times_out(monkeypatch):
    updates = []
    refreshed = []
    brand_info = {"brand": "maurices", "row_index": 11, "brand_url": ""}

    class Button:
        def get_attribute(self, name):
            return None

    class Card:
        text = "maurices Not partnered"

        def find_elements(self, by, loc):
            return []

        def find_element(self, by, loc):
            return Button()

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/advertisers/40158/offers/1786158/details"

        def find_elements(self, by, loc):
            return [Button()]

        def refresh(self):
            refreshed.append(True)

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []) if not brand else (Card(), ["maurices"]))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_search_results", lambda driver, brand, before_titles: ("ready", Card(), ["maurices"]))
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_offer_apply_button", lambda driver, timeout=30: ("ready", Button()))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_send_request_result", lambda driver, timeout=30: "success_message")
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_post_submit_status", lambda driver, timeout=30: "timeout")
    monkeypatch.setattr(rakuten_aff_apply, "_find_el", lambda driver, by, loc, timeout=10: object())
    monkeypatch.setattr(rakuten_aff_apply, "_click_el", lambda driver, element: True)
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(Driver(), brand_info, service="svc", header_map={}) is True
    assert refreshed == [True]
    assert updates == [(11, rakuten_aff_apply.APPLY_STATUS_APPLIED, "Pending (applied)")]


def test_process_brand_application_marks_existing_partnered_card_as_applied(monkeypatch):
    updates = []
    brand_info = {"brand": "Hanes.com", "row_index": 8, "brand_url": ""}

    class Link:
        def get_attribute(self, name):
            return "https://publisher.rakutenadvertising.com/advertisers/24366" if name == "href" else ""

    class Card:
        text = "Hanes.com Partnered"

        def find_elements(self, by, loc):
            return [Link()]

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(
        rakuten_aff_apply,
        "find_exact_match_card",
        lambda driver, brand: (Card(), ["Hanes.com"]) if brand else (None, []),
    )
    monkeypatch.setattr(
        rakuten_aff_apply,
        "wait_for_search_results",
        lambda driver, brand, before_titles: ("ready", Card(), ["Hanes.com"]),
    )
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, brand_url, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(object(), brand_info, service="svc", header_map={}) is True
    assert updates == [
        (
            8,
            "https://publisher.rakutenadvertising.com/advertisers/24366",
            rakuten_aff_apply.APPLY_STATUS_APPLIED,
            "Partnered (already approved)",
        )
    ]


def test_process_brand_application_marks_partnered_page_as_applied(monkeypatch):
    updates = []
    brand_info = {"brand": "Hanes.com", "row_index": 8, "brand_url": ""}

    class Button:
        pass

    class Card:
        text = "Hanes.com Not partnered"

        def find_elements(self, by, loc):
            return []

        def find_element(self, by, loc):
            return Button()

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/advertisers/24366/links"

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []) if not brand else (Card(), ["Hanes.com"]))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_search_results", lambda driver, brand, before_titles: ("ready", Card(), ["Hanes.com"]))
    monkeypatch.setattr(rakuten_aff_apply, "_click_el", lambda driver, element: True)
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_offer_apply_button", lambda driver, timeout=30: ("partnered", None))
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, brand_url, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(Driver(), brand_info, service="svc", header_map={}) is True
    assert updates == [
        (
            8,
            "https://publisher.rakutenadvertising.com/advertisers/24366/links",
            rakuten_aff_apply.APPLY_STATUS_APPLIED,
            "Partnered (already approved)",
        )
    ]


def test_process_brand_application_marks_temporary_declined_as_skipped(monkeypatch):
    updates = []
    brand_info = {"brand": "Mack Weldon", "row_index": 5, "brand_url": ""}

    class Button:
        pass

    class Card:
        text = "Mack Weldon Not partnered"

        def find_elements(self, by, loc):
            return []

        def find_element(self, by, loc):
            return Button()

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/advertisers/44780/offers/702047/details"

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []) if not brand else (Card(), ["Mack Weldon"]))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_search_results", lambda driver, brand, before_titles: ("ready", Card(), ["Mack Weldon"]))
    monkeypatch.setattr(rakuten_aff_apply, "_click_el", lambda driver, element: True)
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_offer_apply_button", lambda driver, timeout=30: ("temporary_declined", None))
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, brand_url, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(Driver(), brand_info, service="svc", header_map={}) is False
    assert updates == [
        (
            5,
            "https://publisher.rakutenadvertising.com/advertisers/44780/offers/702047/details",
            rakuten_aff_apply.APPLY_STATUS_SKIPPED,
            "declined temporary, reapply in 14 days",
        )
    ]


def test_wait_for_search_results_requires_stable_non_matching_titles(monkeypatch):
    calls = []
    title_snapshots = [
        (None, []),
        (None, ["Falconeri"]),
        (None, ["Falconeri"]),
        (None, ["Falconeri"]),
    ]

    def fake_find_exact_match_card(driver, brand):
        calls.append(brand)
        return title_snapshots.pop(0)

    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", fake_find_exact_match_card)
    monkeypatch.setattr(rakuten_aff_apply, "has_no_search_results_message", lambda driver: False)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)

    result_state, matched_card, current_titles = rakuten_aff_apply.wait_for_search_results(
        object(),
        "Solid & Striped",
        [],
        timeout=10,
    )

    assert result_state == "ready"
    assert matched_card is None
    assert current_titles == ["Falconeri"]
    assert calls == ["Solid & Striped", "Solid & Striped", "Solid & Striped", "Solid & Striped"]


def test_process_brand_application_marks_existing_pending_card_as_applied(monkeypatch):
    updates = []
    brand_info = {"brand": "NOAH CLOTHING LLC", "row_index": 4, "brand_url": ""}

    class Link:
        def get_attribute(self, name):
            return "https://publisher.rakutenadvertising.com/advertisers/45632" if name == "href" else ""

    class Card:
        text = "NOAH CLOTHING LLC Partnership pending approval"

        def find_elements(self, by, loc):
            return [Link()]

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(
        rakuten_aff_apply,
        "find_exact_match_card",
        lambda driver, brand: (Card(), ["NOAH CLOTHING LLC"]) if brand else (None, []),
    )
    monkeypatch.setattr(
        rakuten_aff_apply,
        "wait_for_search_results",
        lambda driver, brand, before_titles: ("ready", Card(), ["NOAH CLOTHING LLC"]),
    )
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, brand_url, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(object(), brand_info, service="svc", header_map={}) is True
    assert updates == [
        (
            4,
            "https://publisher.rakutenadvertising.com/advertisers/45632",
            rakuten_aff_apply.APPLY_STATUS_APPLIED,
            "Pending (already applied)",
        )
    ]


def test_process_brand_application_marks_terms_not_met_as_skipped(monkeypatch):
    updates = []
    brand_info = {"brand": "Separatec", "row_index": 16, "brand_url": ""}

    class Button:
        pass

    class Card:
        text = "Separatec Not partnered"

        def find_elements(self, by, loc):
            return []

        def find_element(self, by, loc):
            return Button()

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/advertisers/49172/offers/1138773/details"

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []) if not brand else (Card(), ["Separatec"]))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_search_results", lambda driver, brand, before_titles: ("ready", Card(), ["Separatec"]))
    monkeypatch.setattr(rakuten_aff_apply, "_click_el", lambda driver, element: True)
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_offer_apply_button", lambda driver, timeout=30: ("terms_not_met", None))
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, brand_url, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(Driver(), brand_info, service="svc", header_map={}) is False
    assert updates == [
        (
            16,
            "https://publisher.rakutenadvertising.com/advertisers/49172/offers/1138773/details",
            rakuten_aff_apply.APPLY_STATUS_SKIPPED,
            "terms not met",
        )
    ]


def test_process_brand_application_marks_permanent_declined_as_skipped(monkeypatch):
    updates = []
    brand_info = {"brand": "A.P.C. US", "row_index": 43, "brand_url": ""}

    class Button:
        pass

    class Card:
        text = "A.P.C. US Not partnered"

        def find_elements(self, by, loc):
            return []

        def find_element(self, by, loc):
            return Button()

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/advertisers/50509/offers/2018629/details"

    monkeypatch.setattr(rakuten_aff_apply, "open_search_page", lambda driver: True)
    monkeypatch.setattr(rakuten_aff_apply, "search_brand", lambda driver, brand: True)
    monkeypatch.setattr(rakuten_aff_apply, "find_exact_match_card", lambda driver, brand: (None, []) if not brand else (Card(), ["A.P.C. US"]))
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_search_results", lambda driver, brand, before_titles: ("ready", Card(), ["A.P.C. US"]))
    monkeypatch.setattr(rakuten_aff_apply, "_click_el", lambda driver, element: True)
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rakuten_aff_apply, "wait_for_offer_apply_button", lambda driver, timeout=30: ("permanent_declined", None))
    monkeypatch.setattr(
        rakuten_aff_apply,
        "update_branlist_row",
        lambda row_index, header_map, brand_url, apply_status, note, service=None: updates.append(
            (row_index, brand_url, apply_status, note)
        ),
    )

    assert rakuten_aff_apply.process_brand_application(Driver(), brand_info, service="svc", header_map={}) is False
    assert updates == [
        (
            43,
            "https://publisher.rakutenadvertising.com/advertisers/50509/offers/2018629/details",
            rakuten_aff_apply.APPLY_STATUS_SKIPPED,
            "declined permanent",
        )
    ]


def test_process_respects_num_as_processed_brand_limit(monkeypatch):
    processed = []
    logs = []

    class Driver:
        current_url = "https://publisher.rakutenadvertising.com/"

        def set_page_load_timeout(self, timeout):
            return None

        def get(self, url):
            self.current_url = url

    brands = [
        {"brand": "Solid & Striped", "row_index": 62, "brand_url": "", "apply_status": ""},
        {"brand": "Falconeri", "row_index": 63, "brand_url": "", "apply_status": ""},
    ]
    window = {
        "window_start_dt": rakuten_aff_apply.now_dt(),
        "window_end_dt": rakuten_aff_apply.now_dt(),
        "limit_value": 37,
    }

    monkeypatch.setattr(rakuten_aff_apply, "open_env_by_serial", lambda env_serial: (Driver(), "env-1"))
    monkeypatch.setattr(rakuten_aff_apply, "get_sheets_service", lambda: "svc")
    monkeypatch.setattr(rakuten_aff_apply, "_wait_page_full_load", lambda driver, timeout=30: True)
    monkeypatch.setattr(rakuten_aff_apply, "login_rakuten", lambda driver, email=None, password=None: True)
    monkeypatch.setattr(rakuten_aff_apply, "read_branlist_data", lambda service, subject_id, env_serial: (brands, {}))
    monkeypatch.setattr(rakuten_aff_apply, "select_or_create_window", lambda service, subject_id, env_serial: window)
    monkeypatch.setattr(rakuten_aff_apply, "read_apply_logs", lambda service, subject_id: [])
    monkeypatch.setattr(rakuten_aff_apply, "count_used_slots", lambda apply_logs, apply_window: 0)
    monkeypatch.setattr(rakuten_aff_apply, "append_apply_log", lambda record, service=None: logs.append(record))
    monkeypatch.setattr(rakuten_aff_apply.time, "sleep", lambda seconds: None)

    def fake_process_brand_application(driver, brand_info, service=None, header_map=None):
        processed.append(brand_info["brand"])
        return False

    monkeypatch.setattr(rakuten_aff_apply, "process_brand_application", fake_process_brand_application)

    assert rakuten_aff_apply.process("subject@test.com", "6", limit=1) is True
    assert processed == ["Solid & Striped"]
    assert logs == []
