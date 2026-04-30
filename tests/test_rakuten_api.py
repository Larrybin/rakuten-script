import pytest

from lib.errors import ConfigError, RakutenApiError
from lib.rakuten_api import RakutenApiClient, build_token_key


class Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        self.text = str(payload)
        self.reason = "reason"

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


def test_build_token_key_from_client_credentials():
    assert build_token_key("client", "secret") == "Y2xpZW50OnNlY3JldA=="


def test_build_token_key_requires_credentials():
    with pytest.raises(ConfigError):
        build_token_key("", "secret")


def test_from_credentials_requests_access_token():
    session = Session([Response(200, {"access_token": "access-token"})])

    client = RakutenApiClient.from_credentials("account-id", "client", "secret", session=session)

    assert client.access_token == "access-token"
    assert session.calls == [
        (
            "POST",
            "https://api.linksynergy.com/token",
            {
                "headers": {
                    "Authorization": "Bearer Y2xpZW50OnNlY3JldA==",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                "data": {"scope": "account-id"},
                "timeout": 30,
            },
        )
    ]


def test_iter_partnerships_follows_pages():
    session = Session(
        [
            Response(
                200,
                {
                    "metadata": {"links": {"next": "/v1/partnerships?page=2"}},
                    "partnerships": [{"advertiser": {"id": 1}}],
                },
            ),
            Response(200, {"metadata": {"links": {}}, "partnerships": [{"advertiser": {"id": 2}}]}),
        ]
    )
    client = RakutenApiClient("token", session=session)

    partnerships = list(client.iter_partnerships(limit=200))

    assert [item["advertiser"]["id"] for item in partnerships] == [1, 2]
    assert session.calls[0][2]["params"]["partner_status"] == "active"
    assert session.calls[1][2]["params"]["page"] == 2


def test_create_deep_link_returns_deep_link_url():
    session = Session(
        [
            Response(
                200,
                {
                    "advertiser": {
                        "deep_link": {
                            "deep_link_url": "https://click.linksynergy.com/deeplink?id=1",
                        }
                    }
                },
            )
        ]
    )
    client = RakutenApiClient("token", session=session)

    result = client.create_deep_link("123", "https://brand.example", "homepage")

    assert result == "https://click.linksynergy.com/deeplink?id=1"
    assert session.calls[0][2]["json"] == {
        "url": "https://brand.example",
        "advertiser_id": 123,
        "u1": "homepage",
    }


def test_get_text_links_parses_single_link_locator_xml_record():
    session = Session(
        [
            Response(
                200,
                """
                <getTextLinksResponse>
                  <return>
                    <clickURL>https://click.linksynergy.com/text</clickURL>
                    <landURL>https://brand.example/</landURL>
                    <linkName>Homepage</linkName>
                    <textDisplay>Shop Brand</textDisplay>
                    <categoryName>Default</categoryName>
                    <endDate>2099-12-31</endDate>
                  </return>
                </getTextLinksResponse>
                """,
            )
        ]
    )
    client = RakutenApiClient("token", session=session)

    links = client.get_text_links("123", page=2)

    assert links == [
        {
            "clickURL": "https://click.linksynergy.com/text",
            "landURL": "https://brand.example/",
            "linkName": "Homepage",
            "textDisplay": "Shop Brand",
            "categoryName": "Default",
            "endDate": "2099-12-31",
        }
    ]
    assert session.calls[0][1] == (
        "https://api.linksynergy.com/linklocator/1.0/"
        "getTextLinks/123/-1/01012000/12312099/-1/2"
    )


def test_get_banner_links_parses_multiple_link_locator_xml_records():
    session = Session(
        [
            Response(
                200,
                """
                <ns:getBannerLinksResponse xmlns:ns="urn:linklocator">
                  <return>
                    <clickURL>https://click.linksynergy.com/banner-1</clickURL>
                    <landURL>https://brand.example/sale</landURL>
                    <linkName>Sale Banner</linkName>
                  </return>
                  <return>
                    <clickURL>https://click.linksynergy.com/banner-2</clickURL>
                    <landURL>https://brand.example/</landURL>
                    <linkName>Homepage Banner</linkName>
                  </return>
                </ns:getBannerLinksResponse>
                """,
            )
        ]
    )
    client = RakutenApiClient("token", session=session)

    links = client.get_banner_links("123")

    assert [link["clickURL"] for link in links] == [
        "https://click.linksynergy.com/banner-1",
        "https://click.linksynergy.com/banner-2",
    ]
    assert session.calls[0][1] == (
        "https://api.linksynergy.com/linklocator/1.0/"
        "getBannerLinks/123/-1/01012000/12312099/-1/-1/1"
    )


def test_api_error_uses_response_message():
    session = Session([Response(400, {"errors": [{"code": "ACCESS_DENIED", "message": "Not partnered"}]})])
    client = RakutenApiClient("token", session=session)

    with pytest.raises(RakutenApiError, match="ACCESS_DENIED Not partnered"):
        client.get("/v1/partnerships")
