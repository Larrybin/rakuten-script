from types import SimpleNamespace

import pytest

from lib.errors import RakutenApiError
from scripts import sync_partnership_deeplinks


def make_args():
    return SimpleNamespace(
        env_serial=None,
        max_brands=None,
        network=None,
        page_size=200,
        rakuten_account=None,
        sleep=0,
        subject_id="subject@test.com",
        u1="homepage",
    )


def patch_base(monkeypatch, existing, client):
    written = []
    monkeypatch.setattr(sync_partnership_deeplinks, "get_google_spreadsheet_id", lambda: "sheet-id")
    monkeypatch.setattr(sync_partnership_deeplinks, "get_sheets_service", lambda: "service")
    monkeypatch.setattr(sync_partnership_deeplinks, "ensure_runtime_sheets", lambda spreadsheet_id, service: None)
    monkeypatch.setattr(
        sync_partnership_deeplinks,
        "read_existing_rows",
        lambda spreadsheet_id, service: (existing, {}),
    )
    subject = SimpleNamespace(
        subject_id="subject@test.com",
        env_serial="3",
        rakuten_account_id="account-id",
        rakuten_client_id="client-id",
        rakuten_client_secret="client-secret",
    )
    monkeypatch.setattr(sync_partnership_deeplinks, "resolve_subject", lambda spreadsheet_id, service, args: subject)

    def fake_from_credentials(account_id, client_id, client_secret):
        assert (account_id, client_id, client_secret) == ("account-id", "client-id", "client-secret")
        return client

    monkeypatch.setattr(
        sync_partnership_deeplinks.RakutenApiClient,
        "from_credentials",
        fake_from_credentials,
    )
    monkeypatch.setattr(
        sync_partnership_deeplinks,
        "upsert_deeplink_row",
        lambda spreadsheet_id, service, rows, header_map, record: written.append(record),
    )
    return written


class Client:
    def __init__(
        self,
        partnerships,
        advertiser=None,
        advertiser_error=None,
        deeplink=None,
        deeplink_error=None,
        text_links=None,
        banner_links=None,
    ):
        self.partnerships = partnerships
        self.advertiser = advertiser or {}
        self.advertiser_error = advertiser_error
        self.deeplink = deeplink or "https://click.linksynergy.com/new"
        self.deeplink_error = deeplink_error
        self.text_links = text_links or []
        self.banner_links = banner_links or []
        self.deep_link_calls = []
        self.text_link_calls = []
        self.banner_link_calls = []
        self.get_advertiser_calls = 0

    def iter_partnerships(self, network=None, limit=200):
        return iter(self.partnerships)

    def get_advertiser(self, advertiser_id):
        self.get_advertiser_calls += 1
        if self.advertiser_error:
            error = self.advertiser_error.pop(0) if isinstance(self.advertiser_error, list) else self.advertiser_error
            if error:
                raise error
        return self.advertiser

    def create_deep_link(self, advertiser_id, url, u1=""):
        self.deep_link_calls.append((advertiser_id, url, u1))
        if self.deeplink_error:
            error = self.deeplink_error.pop(0) if isinstance(self.deeplink_error, list) else self.deeplink_error
            if error:
                raise error
        return self.deeplink

    def get_text_links(self, advertiser_id, page=1):
        self.text_link_calls.append((advertiser_id, page))
        return self.text_links[page - 1] if page <= len(self.text_links) else []

    def get_banner_links(self, advertiser_id, page=1):
        self.banner_link_calls.append((advertiser_id, page))
        return self.banner_links[page - 1] if page <= len(self.banner_links) else []


def partnership():
    return {
        "advertiser": {"id": 123, "name": "Brand", "status": "active"},
        "status": "active",
        "approve_datetime": "2026-01-01T00:00:00Z",
        "status_update_datetime": "2026-01-02T00:00:00Z",
    }


def existing_row():
    return {
        "row_index": "2",
        "subject_id": "subject@test.com",
        "advertiser_id": "123",
        "advertiser_name": "Brand",
        "advertiser_url": "https://brand.example",
        "partnership_status": "active",
        "advertiser_status": "active",
        "deep_links_enabled": "true",
        "homepage_deeplink": "https://click.linksynergy.com/old",
        "u1": "homepage",
        "approved_at": "2026-01-01T00:00:00Z",
        "status_updated_at": "2026-01-02T00:00:00Z",
        "synced_at": "old-sync",
        "note": "ok",
    }


def test_create_deep_link_error_keeps_existing_homepage_deeplink(monkeypatch):
    existing = {("subject@test.com", "123"): existing_row()}
    client = Client(
        [partnership()],
        advertiser={"id": 123, "name": "Brand", "url": "https://brand.example", "features": {"deep_links": True}},
        deeplink_error=RakutenApiError("temporary failure"),
    )
    written = patch_base(monkeypatch, existing, client)

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0

    assert written[0]["advertiser_url"] == "https://brand.example"
    assert written[0]["deep_links_enabled"] == "true"
    assert written[0]["homepage_deeplink"] == "https://click.linksynergy.com/old"
    assert written[0]["note"] == "api error: temporary failure"


def test_get_advertiser_error_keeps_existing_advertiser_fields(monkeypatch):
    existing = {("subject@test.com", "123"): existing_row()}
    client = Client([partnership()], advertiser_error=RakutenApiError("temporary failure"))
    written = patch_base(monkeypatch, existing, client)

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0

    assert written[0]["advertiser_url"] == "https://brand.example"
    assert written[0]["deep_links_enabled"] == "true"
    assert written[0]["homepage_deeplink"] == "https://click.linksynergy.com/old"
    assert written[0]["note"] == "api error: temporary failure"


def test_empty_partnerships_is_success(monkeypatch):
    written = patch_base(monkeypatch, {}, Client([]))

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0
    assert written == []


def test_deep_links_disabled_clears_existing_homepage_deeplink(monkeypatch):
    existing = {("subject@test.com", "123"): existing_row()}
    client = Client(
        [partnership()],
        advertiser={"id": 123, "name": "Brand", "url": "https://brand.example", "features": {"deep_links": False}},
    )
    written = patch_base(monkeypatch, existing, client)

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0

    assert written[0]["advertiser_url"] == "https://brand.example"
    assert written[0]["deep_links_enabled"] == "false"
    assert written[0]["homepage_deeplink"] == ""
    assert written[0]["note"] == "deep links disabled; no link locator fallback"


def test_advertiser_ships_to_is_written_as_comma_separated_country_codes(monkeypatch):
    client = Client(
        [partnership()],
        advertiser={
            "id": 123,
            "name": "Brand",
            "url": "https://brand.example",
            "policies": {"international_capabilities": {"ships_to": ["US", "CA", "JP"]}},
            "features": {"deep_links": True},
        },
    )
    written = patch_base(monkeypatch, {}, client)

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0

    assert written[0]["ships_to"] == "US,CA,JP"


def test_deep_links_disabled_uses_text_link_fallback(monkeypatch):
    existing = {("subject@test.com", "123"): existing_row()}
    client = Client(
        [partnership()],
        advertiser={"id": 123, "name": "Brand", "url": "https://brand.example", "features": {"deep_links": False}},
        text_links=[
            [
                {
                    "clickURL": "https://click.linksynergy.com/text",
                    "landURL": "https://brand.example/",
                    "linkName": "Homepage",
                    "textDisplay": "Shop Brand",
                    "categoryName": "Default",
                    "endDate": "2099-12-31",
                }
            ]
        ],
    )
    written = patch_base(monkeypatch, existing, client)

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0

    assert written[0]["homepage_deeplink"] == "https://click.linksynergy.com/text"
    assert written[0]["note"] == "ok via link locator text"
    assert client.text_link_calls[:1] == [("123", 1)]
    assert client.banner_link_calls == []


def test_url_template_mismatch_uses_text_link_fallback(monkeypatch):
    client = Client(
        [partnership()],
        advertiser={"id": 123, "name": "Brand", "url": "https://brand.example", "features": {"deep_links": True}},
        deeplink_error=RakutenApiError("URL_TEMPLATE_MISMATCH"),
        text_links=[
            [
                {
                    "clickURL": "https://click.linksynergy.com/text",
                    "landURL": "https://brand.example/",
                    "linkName": "Homepage",
                }
            ]
        ],
    )
    written = patch_base(monkeypatch, {}, client)

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0

    assert written[0]["homepage_deeplink"] == "https://click.linksynergy.com/text"
    assert written[0]["note"] == "ok via link locator text"


def test_link_locator_uses_banner_when_text_fallback_is_empty(monkeypatch):
    client = Client(
        [partnership()],
        advertiser={"id": 123, "name": "Brand", "url": "https://brand.example", "features": {"deep_links": False}},
        text_links=[[]],
        banner_links=[
            [
                {
                    "clickURL": "https://click.linksynergy.com/banner",
                    "landURL": "https://brand.example/",
                    "linkName": "Default Banner",
                }
            ]
        ],
    )
    written = patch_base(monkeypatch, {}, client)

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0

    assert written[0]["homepage_deeplink"] == "https://click.linksynergy.com/banner"
    assert written[0]["note"] == "ok via link locator banner"
    assert client.text_link_calls == [("123", 1)]
    assert client.banner_link_calls[:1] == [("123", 1)]


def test_url_template_mismatch_without_link_locator_keeps_failure_note(monkeypatch):
    client = Client(
        [partnership()],
        advertiser={"id": 123, "name": "Brand", "url": "https://brand.example", "features": {"deep_links": True}},
        deeplink_error=RakutenApiError("URL_TEMPLATE_MISMATCH"),
    )
    written = patch_base(monkeypatch, {}, client)

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0

    assert written[0]["homepage_deeplink"] == ""
    assert written[0]["note"] == "api error: URL_TEMPLATE_MISMATCH; no link locator fallback"


def test_homepage_url_without_scheme_is_normalized_before_deep_link(monkeypatch):
    client = Client(
        [partnership()],
        advertiser={"id": 123, "name": "Brand", "url": "www.brand.example", "features": {"deep_links": True}},
    )
    written = patch_base(monkeypatch, {}, client)

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0

    assert written[0]["advertiser_url"] == "https://www.brand.example"
    assert written[0]["homepage_deeplink"] == "https://click.linksynergy.com/new"
    assert client.deep_link_calls == [("123", "https://www.brand.example", "homepage")]


def test_transient_deep_link_error_is_retried(monkeypatch):
    client = Client(
        [partnership()],
        advertiser={"id": 123, "name": "Brand", "url": "https://brand.example", "features": {"deep_links": True}},
        deeplink_error=[RakutenApiError("Read timed out"), None],
    )
    written = patch_base(monkeypatch, {}, client)

    assert sync_partnership_deeplinks.sync_partnership_deeplinks(make_args()) == 0

    assert written[0]["homepage_deeplink"] == "https://click.linksynergy.com/new"
    assert written[0]["note"] == "ok"
    assert len(client.deep_link_calls) == 2
