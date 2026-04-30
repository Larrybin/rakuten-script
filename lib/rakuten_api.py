from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urljoin

import requests

from lib.errors import ConfigError, RakutenApiError

API_BASE_URL = "https://api.linksynergy.com"
LINK_LOCATOR_START_DATE = "01012000"
LINK_LOCATOR_END_DATE = "12312099"


class RakutenApiClient:
    def __init__(self, access_token: str, session=None, api_base_url: str = API_BASE_URL):
        token = (access_token or "").strip()
        if not token:
            raise ConfigError("缺少 Rakuten API access token")
        self.access_token = token
        self.session = session or requests.Session()
        self.api_base_url = api_base_url.rstrip("/")

    @classmethod
    def from_credentials(cls, account_id: str, client_id: str, client_secret: str, session=None):
        account_id = (account_id or "").strip()
        token_key = build_token_key(client_id, client_secret)
        if not account_id:
            raise ConfigError("King 缺少 RAKUTEN_ACCOUNT_ID")
        token_payload = cls.generate_access_token(token_key, account_id, session=session)
        return cls(token_payload["access_token"], session=session)

    @staticmethod
    def generate_access_token(token_key: str, account_id: str, session=None) -> Dict[str, Any]:
        current_session = session or requests.Session()
        try:
            response = current_session.post(
                f"{API_BASE_URL}/token",
                headers={
                    "Authorization": f"Bearer {token_key}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scope": account_id},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RakutenApiError(f"Rakuten token 请求失败: {exc}") from exc
        data = _parse_response(response)
        if not data.get("access_token"):
            raise RakutenApiError("Rakuten token 响应缺少 access_token")
        return data

    def iter_partnerships(
        self,
        partner_status: str = "active",
        advertiser_status: str = "active",
        network: Optional[str] = None,
        limit: int = 200,
    ) -> Iterable[Dict[str, Any]]:
        page = 1
        while True:
            params = {
                "partner_status": partner_status,
                "advertiser_status": advertiser_status,
                "limit": limit,
                "page": page,
            }
            if network:
                params["network"] = network
            data = self.get("/v1/partnerships", params=params)
            partnerships = data.get("partnerships") or []
            for item in partnerships:
                yield item
            if not _has_next_page(data, page, len(partnerships), limit):
                return
            page += 1

    def get_advertiser(self, advertiser_id: str) -> Dict[str, Any]:
        data = self.get(f"/v2/advertisers/{advertiser_id}")
        return data.get("advertiser") or {}

    def create_deep_link(self, advertiser_id: str, url: str, u1: str = "") -> str:
        payload: Dict[str, Any] = {"url": url, "advertiser_id": int(advertiser_id)}
        if u1:
            payload["u1"] = u1
        data = self.post("/v1/links/deep_links", json=payload)
        advertiser = data.get("advertiser") or {}
        deep_link = advertiser.get("deep_link") or {}
        deep_link_url = deep_link.get("deep_link_url") or ""
        if not deep_link_url:
            raise RakutenApiError("Deep Links API 响应缺少 deep_link_url")
        return deep_link_url

    def get_text_links(self, advertiser_id: str, page: int = 1):
        xml = self._request_text(
            "GET",
            f"/linklocator/1.0/getTextLinks/"
            f"{advertiser_id}/-1/{LINK_LOCATOR_START_DATE}/{LINK_LOCATOR_END_DATE}/-1/{page}",
        )
        return parse_link_locator_xml(xml)

    def get_banner_links(self, advertiser_id: str, page: int = 1):
        xml = self._request_text(
            "GET",
            f"/linklocator/1.0/getBannerLinks/"
            f"{advertiser_id}/-1/{LINK_LOCATOR_START_DATE}/{LINK_LOCATOR_END_DATE}/-1/-1/{page}",
        )
        return parse_link_locator_xml(xml)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("POST", path, json=json)

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = urljoin(f"{self.api_base_url}/", path.lstrip("/"))
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            response = self.session.request(method, url, headers=headers, timeout=30, **kwargs)
        except requests.RequestException as exc:
            raise RakutenApiError(f"Rakuten API 请求失败 {method} {path}: {exc}") from exc
        return _parse_response(response)

    def _request_text(self, method: str, path: str, **kwargs) -> str:
        url = urljoin(f"{self.api_base_url}/", path.lstrip("/"))
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            response = self.session.request(method, url, headers=headers, timeout=30, **kwargs)
        except requests.RequestException as exc:
            raise RakutenApiError(f"Rakuten API 请求失败 {method} {path}: {exc}") from exc
        if 200 <= response.status_code < 300:
            return getattr(response, "text", "")
        _parse_response(response)
        return ""


def build_token_key(client_id: str, client_secret: str) -> str:
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        raise ConfigError("King 缺少 RAKUTEN_CLIENT_ID 或 RAKUTEN_CLIENT_SECRET")
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def parse_link_locator_xml(xml_text: str):
    text = (xml_text or "").strip()
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise RakutenApiError(f"Link Locator XML 响应无法解析: {exc}") from exc

    links = []
    for item in root.iter():
        if _xml_tag_name(item.tag) != "return":
            continue
        link = {}
        for child in list(item):
            value = (child.text or "").strip()
            if value:
                link[_xml_tag_name(child.tag)] = value
        if link:
            links.append(link)
    return links


def _xml_tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_response(response) -> Dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        data = {}
    if 200 <= response.status_code < 300:
        return data

    message = _error_message(data) or getattr(response, "text", "").strip() or getattr(response, "reason", "")
    raise RakutenApiError(f"Rakuten API HTTP {response.status_code}: {message}")


def _error_message(data: Dict[str, Any]) -> str:
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            code = first.get("code") or first.get("error") or ""
            message = first.get("message") or first.get("description") or ""
            return " ".join(str(item) for item in [code, message] if item)
        return str(first)
    for key in ["error_description", "error", "message"]:
        if data.get(key):
            return str(data[key])
    return ""


def _has_next_page(data: Dict[str, Any], page: int, count: int, limit: int) -> bool:
    metadata = data.get("metadata") or data.get("_metadata") or {}
    links = metadata.get("links") or metadata.get("_links") or {}
    if links.get("next"):
        return True

    total = metadata.get("total")
    try:
        return page * limit < int(total)
    except (TypeError, ValueError):
        return count >= limit
