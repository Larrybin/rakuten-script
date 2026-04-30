from unittest.mock import MagicMock

import pytest
import requests
from selenium.common.exceptions import NoSuchWindowException, WebDriverException

from lib import fingerprint_utils as helper
from lib.errors import AdsPowerApiError, AdsPowerLaunchError


def setup_function():
    helper._PROFILE_CACHE.clear()
    helper._PROFILE_LIST_CACHE = None


def test_get_existing_env_info_hits_serial_number(monkeypatch):
    monkeypatch.setattr(
        helper,
        "_get_profile_by_narrow_query",
        lambda key: {"profile_id": "pid-1", "serial_number": "3"},
    )

    result = helper.get_existing_env_info("3")
    assert result["env_id"] == "pid-1"
    assert result["profile_id"] == "pid-1"
    assert result["serial_number"] == "3"


def test_get_existing_env_info_fallback_profile_id(monkeypatch):
    monkeypatch.setattr(helper, "_get_profile_by_narrow_query", lambda key: None)
    monkeypatch.setattr(
        helper,
        "_get_profiles_via_list",
        lambda: [{"profile_id": "pid-2", "serial_number": "9"}],
    )

    result = helper.get_existing_env_info("pid-2")
    assert result["env_id"] == "pid-2"
    assert result["profile_id"] == "pid-2"


def test_extract_profiles_keeps_name_for_runtime_migration():
    payload = {
        "data": {
            "list": [
                {
                    "user_id": "pid-3",
                    "serial_number": "306",
                    "name": "Z117",
                }
            ]
        }
    }

    profiles = helper._extract_profiles(payload)

    assert profiles == [
        {
            "profile_id": "pid-3",
            "serial_number": "306",
            "name": "Z117",
        }
    ]


def test_get_profiles_via_list_paginates_until_end(monkeypatch):
    calls = []
    page_size = helper._PROFILE_LIST_PAGE_SIZE

    def fake_request(method, path, *, params=None, json=None):
        calls.append((method, path, params))
        page = params["page"]
        if page == 1:
            return {
                "data": {
                    "list": [
                        {"user_id": f"pid-a-{idx}", "serial_number": f"10{idx}", "name": f"A{idx}"}
                        for idx in range(page_size)
                    ],
                    "page": 1,
                    "page_size": page_size,
                },
                "code": 0,
            }
        if page == 2:
            return {
                "data": {
                    "list": [
                        {"user_id": f"pid-b-{idx}", "serial_number": f"20{idx}", "name": f"B{idx}"}
                        for idx in range(page_size)
                    ],
                    "page": 2,
                    "page_size": page_size,
                },
                "code": 0,
            }
        return {"data": {"list": [], "page": page, "page_size": page_size}, "code": 0}

    monkeypatch.setattr(helper, "_request", fake_request)

    profiles = helper._get_profiles_via_list()

    assert len(profiles) == page_size * 2
    assert calls == [
        ("GET", "/api/v1/user/list", {"page": 1, "page_size": page_size}),
        ("GET", "/api/v1/user/list", {"page": 2, "page_size": page_size}),
        ("GET", "/api/v1/user/list", {"page": 3, "page_size": page_size}),
    ]


def test_get_profiles_via_list_stops_when_page_is_short(monkeypatch):
    calls = []

    def fake_request(method, path, *, params=None, json=None):
        calls.append((method, path, params))
        return {
            "data": {
                "list": [{"user_id": "pid-1", "serial_number": "101", "name": "A"}],
            },
            "code": 0,
        }

    monkeypatch.setattr(helper, "_request", fake_request)

    profiles = helper._get_profiles_via_list()

    assert profiles == [{"profile_id": "pid-1", "serial_number": "101", "name": "A"}]
    assert calls == [("GET", "/api/v1/user/list", {"page": 1, "page_size": 100})]


def test_get_profiles_via_list_stops_when_page_repeats(monkeypatch):
    calls = []
    page_size = helper._PROFILE_LIST_PAGE_SIZE

    def fake_request(method, path, *, params=None, json=None):
        calls.append((method, path, params))
        return {
            "data": {
                "list": [
                    {"user_id": f"pid-{idx}", "serial_number": str(idx), "name": f"A{idx}"}
                    for idx in range(page_size)
                ],
            },
            "code": 0,
        }

    monkeypatch.setattr(helper, "_request", fake_request)
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: None)

    profiles = helper._get_profiles_via_list()

    assert len(profiles) == page_size
    assert calls == [
        ("GET", "/api/v1/user/list", {"page": 1, "page_size": page_size}),
        ("GET", "/api/v1/user/list", {"page": 2, "page_size": page_size}),
    ]


def test_get_profiles_via_list_raises_when_max_pages_reached(monkeypatch):
    page_size = helper._PROFILE_LIST_PAGE_SIZE

    def fake_request(method, path, *, params=None, json=None):
        page = params["page"]
        return {
            "data": {
                "list": [
                    {
                        "user_id": f"{path}-pid-{page}-{idx}",
                        "serial_number": f"{page}-{idx}",
                        "name": f"A{page}-{idx}",
                    }
                    for idx in range(page_size)
                ],
            },
            "code": 0,
        }

    monkeypatch.setattr(helper, "_request", fake_request)
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(helper, "_PROFILE_LIST_MAX_PAGES", 2)

    with pytest.raises(AdsPowerApiError):
        helper._get_profiles_via_list()


def test_get_profiles_via_list_retries_after_rate_limit(monkeypatch):
    calls = []
    sleep_calls = []

    def fake_request(method, path, *, params=None, json=None):
        calls.append((method, path, params))
        if len(calls) == 1:
            raise AdsPowerApiError("AdsPower 返回失败: {'code': -1, 'msg': 'Too many request per second, please check'}")
        if len(calls) == 2:
            return {
                "data": {
                    "list": [{"user_id": "pid-1", "serial_number": "101", "name": "A"}],
                    "page": 1,
                    "page_size": 100,
                },
                "code": 0,
            }
        return {"data": {"list": [], "page": 2, "page_size": 100}, "code": 0}

    monkeypatch.setattr(helper, "_request", fake_request)
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    profiles = helper._get_profiles_via_list()

    assert profiles == [{"profile_id": "pid-1", "serial_number": "101", "name": "A"}]
    assert sleep_calls == [1]


def test_get_existing_env_info_not_found(monkeypatch):
    monkeypatch.setattr(helper, "_get_profile_by_narrow_query", lambda key: None)
    monkeypatch.setattr(helper, "_get_profiles_via_list", lambda: [])

    with pytest.raises(AdsPowerApiError):
        helper.get_existing_env_info("missing")


def test_open_env_with_retry_v2_debug_port_success(monkeypatch):
    monkeypatch.setattr(helper, "_start_profile_v2", lambda profile_id: ({}, "9222", None, None))
    monkeypatch.setattr(helper, "_wait_for_debug_port", lambda debug_port, timeout=10: None)

    def fake_chrome(*, options):
        driver = MagicMock()
        driver.set_page_load_timeout = MagicMock()
        assert options.debugger_address == "127.0.0.1:9222"
        return driver

    monkeypatch.setattr(helper.webdriver, "Chrome", fake_chrome)

    driver = helper.open_env_with_retry("pid-1")
    assert driver is not None


def test_open_env_with_retry_v2_fail_v1_success(monkeypatch):
    monkeypatch.setattr(helper, "_start_profile_v2", lambda profile_id: (_ for _ in ()).throw(AdsPowerApiError("v2 fail")))
    monkeypatch.setattr(helper, "_start_profile_v1", lambda profile_id: ({}, "9333", None, None))
    monkeypatch.setattr(helper, "_wait_for_debug_port", lambda debug_port, timeout=10: None)
    monkeypatch.setattr(helper.webdriver, "Chrome", lambda *, options: MagicMock(set_page_load_timeout=MagicMock()))

    driver = helper.open_env_with_retry("pid-1")
    assert driver is not None


def test_open_env_with_retry_remote_fallback(monkeypatch):
    monkeypatch.setattr(helper, "_start_profile_v2", lambda profile_id: ({}, None, "http://127.0.0.1:4444/wd/hub", None))
    monkeypatch.setattr(helper.webdriver, "Remote", lambda command_executor: MagicMock(set_page_load_timeout=MagicMock()))

    driver = helper.open_env_with_retry("pid-1")
    assert driver is not None


def test_open_env_with_retry_attach_failure(monkeypatch):
    monkeypatch.setattr(helper, "_start_profile_v2", lambda profile_id: ({}, "9222", None, None))
    monkeypatch.setattr(helper, "_wait_for_debug_port", lambda debug_port, timeout=10: None)

    def broken_chrome(*, options):
        raise WebDriverException("attach failed")

    monkeypatch.setattr(helper.webdriver, "Chrome", broken_chrome)

    with pytest.raises(AdsPowerLaunchError):
        helper.open_env_with_retry("pid-1")


def test_open_env_with_retry_waits_for_transient_startup(monkeypatch):
    attempts = {"count": 0}
    sleep_calls = []

    def fake_start_v2(profile_id):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise AdsPowerApiError("SunBrowser 144 is updating, waiting for download.")
        return ({}, "9555", None, None)

    monkeypatch.setattr(helper, "_start_profile_v2", fake_start_v2)
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(helper, "_wait_for_debug_port", lambda debug_port, timeout=10: None)
    monkeypatch.setattr(
        helper.webdriver,
        "Chrome",
        lambda *, options: MagicMock(set_page_load_timeout=MagicMock()),
    )

    driver = helper.open_env_with_retry("pid-1", max_retries=2)
    assert driver is not None
    assert attempts["count"] == 2
    assert sleep_calls == [5]


def test_open_env_with_retry_retries_when_attached_window_is_closed(monkeypatch):
    monkeypatch.setattr(helper, "_start_profile_v2", lambda profile_id: ({}, "9555", None, None))
    monkeypatch.setattr(helper, "_wait_for_debug_port", lambda debug_port, timeout=10: None)

    attempts = {"count": 0}
    sleep_calls = []

    class BrokenSwitchTo:
        def window(self, handle):
            raise NoSuchWindowException("window gone")

    def fake_chrome(*, options):
        attempts["count"] += 1
        driver = MagicMock()
        driver.set_page_load_timeout = MagicMock()
        if attempts["count"] == 1:
            type(driver).window_handles = property(lambda self: ["broken-handle"])
            driver.switch_to = BrokenSwitchTo()
        else:
            type(driver).window_handles = property(lambda self: ["ok-handle"])
            driver.switch_to.window = MagicMock()
            type(driver).current_url = property(lambda self: "https://start.adspower.net/")
        return driver

    monkeypatch.setattr(helper.webdriver, "Chrome", fake_chrome)
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    driver = helper.open_env_with_retry("pid-1", max_retries=2)

    assert driver is not None
    assert attempts["count"] == 2
    assert sleep_calls == [1]


def test_open_env_with_retry_prefers_adspower_webdriver(monkeypatch):
    monkeypatch.setattr(
        helper,
        "_start_profile_v2",
        lambda profile_id: ({}, "9222", None, "/tmp/adspower/chromedriver"),
    )
    monkeypatch.setattr(helper, "_wait_for_debug_port", lambda debug_port, timeout=10: None)

    created_services = []

    def fake_service(*, executable_path):
        created_services.append(executable_path)
        return MagicMock()

    attempts = []

    def fake_chrome(*, options, service=None):
        attempts.append(service is not None)
        driver = MagicMock()
        driver.set_page_load_timeout = MagicMock()
        return driver

    monkeypatch.setattr(helper, "Service", fake_service)
    monkeypatch.setattr(helper.webdriver, "Chrome", fake_chrome)

    driver = helper.open_env_with_retry("pid-1")
    assert driver is not None
    assert attempts == [True]
    assert created_services == ["/tmp/adspower/chromedriver"]


def test_open_env_with_retry_falls_back_to_selenium_manager_when_adspower_webdriver_fails(monkeypatch):
    monkeypatch.setattr(
        helper,
        "_start_profile_v2",
        lambda profile_id: ({}, "9222", None, "/tmp/adspower/chromedriver"),
    )
    monkeypatch.setattr(helper, "_wait_for_debug_port", lambda debug_port, timeout=10: None)

    created_services = []
    attempts = []

    def fake_service(*, executable_path):
        created_services.append(executable_path)
        return MagicMock()

    def fake_chrome(*, options, service=None):
        attempts.append(service is not None)
        if service is not None:
            raise WebDriverException("driver path broken")
        driver = MagicMock()
        driver.set_page_load_timeout = MagicMock()
        return driver

    monkeypatch.setattr(helper, "Service", fake_service)
    monkeypatch.setattr(helper.webdriver, "Chrome", fake_chrome)

    driver = helper.open_env_with_retry("pid-1")
    assert driver is not None
    assert attempts == [True, False]
    assert created_services == ["/tmp/adspower/chromedriver"]


def test_wait_for_debug_port_polls_until_json_version_ready(monkeypatch):
    calls = []

    class DummyResponse:
        status_code = 200

    def fake_get(url, timeout):
        calls.append((url, timeout))
        if len(calls) < 3:
            raise requests.RequestException("not ready")
        return DummyResponse()

    monkeypatch.setattr(helper.requests, "get", fake_get)
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: None)

    helper._wait_for_debug_port("9222", timeout=3)

    assert calls == [
        ("http://127.0.0.1:9222/json/version", 1),
        ("http://127.0.0.1:9222/json/version", 1),
        ("http://127.0.0.1:9222/json/version", 1),
    ]


def test_stop_env_prefers_v2_and_falls_back_to_v1(monkeypatch):
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/v2/browser-profile/stop":
            raise AdsPowerApiError("v2 stop failed")
        return {"code": 0}

    monkeypatch.setattr(helper, "_request", fake_request)

    helper.stop_env("pid-1")

    assert calls == [
        ("POST", "/api/v2/browser-profile/stop", {"json": {"profile_id": "pid-1"}}),
        ("GET", "/api/v1/browser/stop", {"params": {"user_id": "pid-1"}}),
    ]


def test_set_fullscreen_mode_warn_only(capsys):
    driver = MagicMock()
    driver.maximize_window.side_effect = RuntimeError("boom")
    helper.set_fullscreen_mode(driver)
    captured = capsys.readouterr()
    assert "WARN" in captured.out
