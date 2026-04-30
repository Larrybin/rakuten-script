import time
from typing import Dict, List, Optional

import requests
from selenium import webdriver
from selenium.common.exceptions import NoSuchWindowException, WebDriverException
from selenium.webdriver.chrome.service import Service

from lib.config import get_adspower_api_base, get_adspower_api_key, load_settings
from lib.errors import AdsPowerApiError, AdsPowerError, AdsPowerLaunchError

_PROFILE_CACHE: Dict[str, Dict[str, Optional[str]]] = {}
_PROFILE_LIST_CACHE: Optional[List[Dict[str, Optional[str]]]] = None
_TRANSIENT_STARTUP_MARKERS = (
    "waiting for download",
    "is updating",
    "downloading",
    "please wait",
)
_RATE_LIMIT_MARKERS = (
    "too many request per second",
    "too many requests",
)
_PROFILE_LIST_PAGE_SIZE = 100
_PROFILE_LIST_MAX_PAGES = 100


def preload_fingerprint_cache():
    load_settings()


def _headers() -> Dict[str, str]:
    api_key = get_adspower_api_key()
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _extract_profiles(payload) -> List[Dict[str, Optional[str]]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        source = data
    elif isinstance(data, dict):
        if isinstance(data.get("list"), list):
            source = data["list"]
        elif isinstance(data.get("profiles"), list):
            source = data["profiles"]
        else:
            source = [data]
    else:
        source = []

    profiles = []
    for item in source:
        if not isinstance(item, dict):
            continue
        profile_id = str(
            item.get("profile_id")
            or item.get("user_id")
            or item.get("id")
            or ""
        ).strip()
        serial_number = str(
            item.get("serial_number")
            or item.get("profile_no")
            or item.get("number")
            or ""
        ).strip()
        if profile_id or serial_number:
            profiles.append(
                {
                    "profile_id": profile_id or None,
                    "serial_number": serial_number or None,
                    "name": str(item.get("name") or "").strip() or None,
                }
            )
    return profiles


def _request(method: str, path: str, *, params=None, json=None):
    base = get_adspower_api_base()
    url = f"{base}{path}"
    try:
        response = requests.request(
            method,
            url,
            params=params,
            json=json,
            headers=_headers(),
            timeout=20,
        )
    except requests.RequestException as exc:
        raise AdsPowerApiError(f"调用 AdsPower 失败: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text}

    if response.status_code >= 400:
        raise AdsPowerApiError(f"AdsPower HTTP {response.status_code}: {payload}")

    if isinstance(payload, dict):
        code = payload.get("code")
        if code not in (None, 0, "0", 200):
            raise AdsPowerApiError(f"AdsPower 返回失败: {payload}")
    return payload


def _get_profile_by_narrow_query(env_serial: str) -> Optional[Dict[str, Optional[str]]]:
    candidates = [
        ("/api/v1/user/list", {"serial_number": env_serial}),
        ("/api/v1/user/list", {"profile_id": env_serial}),
        ("/api/v1/browser/list", {"serial_number": env_serial}),
        ("/api/v1/browser/list", {"profile_id": env_serial}),
    ]
    for path, params in candidates:
        try:
            payload = _request("GET", path, params=params)
        except AdsPowerApiError:
            continue
        profiles = _extract_profiles(payload)
        for profile in profiles:
            if profile.get("serial_number") == env_serial or profile.get("profile_id") == env_serial:
                return profile
    return None


def _is_rate_limit_error(exc: AdsPowerApiError) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _RATE_LIMIT_MARKERS)


def _get_profiles_via_list() -> List[Dict[str, Optional[str]]]:
    global _PROFILE_LIST_CACHE
    if _PROFILE_LIST_CACHE is not None:
        return _PROFILE_LIST_CACHE

    candidates = ["/api/v1/user/list", "/api/v1/browser/list"]
    for path in candidates:
        profiles: List[Dict[str, Optional[str]]] = []
        seen_keys = set()
        page = 1
        reached_max_pages = False
        while True:
            if page > _PROFILE_LIST_MAX_PAGES:
                reached_max_pages = True
                break
            try:
                payload = _request("GET", path, params={"page": page, "page_size": _PROFILE_LIST_PAGE_SIZE})
            except AdsPowerApiError as exc:
                if _is_rate_limit_error(exc):
                    time.sleep(1)
                    try:
                        payload = _request("GET", path, params={"page": page, "page_size": _PROFILE_LIST_PAGE_SIZE})
                    except AdsPowerApiError:
                        profiles = []
                        break
                else:
                    profiles = []
                    break
            page_profiles = _extract_profiles(payload)
            if not page_profiles:
                break
            page_keys = {
                (
                    profile.get("profile_id") or "",
                    profile.get("serial_number") or "",
                )
                for profile in page_profiles
            }
            new_keys = page_keys - seen_keys
            if not new_keys:
                break
            profiles.extend(page_profiles)
            seen_keys.update(new_keys)
            if len(page_profiles) < _PROFILE_LIST_PAGE_SIZE:
                break
            page += 1
            time.sleep(0.2)
        if profiles and not reached_max_pages:
            _PROFILE_LIST_CACHE = profiles
            return profiles

    raise AdsPowerApiError(f"无法从 AdsPower 获取 profile 列表，已达到最大页数或接口不可用: {_PROFILE_LIST_MAX_PAGES}")


def get_existing_env_info(env_serial):
    key = str(env_serial).strip()
    if not key:
        raise AdsPowerApiError("env_serial 不能为空")
    if key in _PROFILE_CACHE:
        return _PROFILE_CACHE[key]

    profile = _get_profile_by_narrow_query(key)
    if profile is None:
        profiles = _get_profiles_via_list()
        for item in profiles:
            if item.get("serial_number") == key:
                profile = item
                break
        if profile is None:
            for item in profiles:
                if item.get("profile_id") == key:
                    profile = item
                    break

    if profile is None or not profile.get("profile_id"):
        raise AdsPowerApiError(
            f"未找到 AdsPower profile，已尝试按 serial_number 和 profile_id 匹配: {key}"
        )

    normalized = {
        "env_id": profile["profile_id"],
        "profile_id": profile["profile_id"],
        "serial_number": profile.get("serial_number"),
        "core_version": None,
    }
    _PROFILE_CACHE[key] = normalized
    return normalized


def ensure_chrome_version(env_id, target_version=None, core_version=None):
    print("INFO: AdsPower 模式不处理浏览器内核版本切换")


def _extract_debug_port(payload) -> Optional[str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    candidates = [
        data.get("debug_port"),
        data.get("debugPort"),
        data.get("ws", {}).get("selenium"),
        data.get("webdriver"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text.isdigit():
            return text
        if "127.0.0.1:" in text:
            tail = text.split("127.0.0.1:")[-1]
            return tail.split("/")[0].split(":")[0]
        if text.startswith("http://") or text.startswith("https://"):
            return None
    return None


def _extract_remote_url(payload) -> Optional[str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    candidates = [
        data.get("selenium"),
        data.get("remote_url"),
        data.get("remoteUrl"),
        data.get("webdriver"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text.startswith("http://") or text.startswith("https://"):
            return text
    return None


def _extract_webdriver_path(payload) -> Optional[str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    candidate = data.get("webdriver")
    if candidate is None:
        return None
    text = str(candidate).strip()
    if not text:
        return None
    if text.startswith("http://") or text.startswith("https://"):
        return None
    return text


def _wait_for_debug_port(debug_port: str, timeout: int = 10):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            response = requests.get(f"http://127.0.0.1:{debug_port}/json/version", timeout=1)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(0.5)
    raise AdsPowerLaunchError(f"AdsPower debug_port 未就绪: {debug_port}, last_error={last_error}")


def _is_transient_startup_error(exc: AdsPowerApiError) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_STARTUP_MARKERS)


def _start_profile_v2(profile_id: str):
    payload = _request(
        "POST",
        "/api/v2/browser-profile/start",
        json={"profile_id": profile_id},
    )
    debug_port = _extract_debug_port(payload)
    remote_url = _extract_remote_url(payload)
    webdriver_path = _extract_webdriver_path(payload)
    return payload, debug_port, remote_url, webdriver_path


def _start_profile_v1(profile_id: str):
    payload = _request(
        "GET",
        "/api/v1/browser/start",
        params={"user_id": profile_id},
    )
    debug_port = _extract_debug_port(payload)
    remote_url = _extract_remote_url(payload)
    webdriver_path = _extract_webdriver_path(payload)
    return payload, debug_port, remote_url, webdriver_path


def stop_env(profile_id: str):
    normalized = str(profile_id).strip()
    if not normalized:
        raise AdsPowerApiError("profile_id 不能为空")

    last_error = None
    for method, path, kwargs in [
        ("POST", "/api/v2/browser-profile/stop", {"json": {"profile_id": normalized}}),
        ("GET", "/api/v1/browser/stop", {"params": {"user_id": normalized}}),
    ]:
        try:
            _request(method, path, **kwargs)
            print(f"INFO: 已关闭 AdsPower 指纹环境: {normalized}")
            return
        except AdsPowerApiError as exc:
            last_error = exc
    raise AdsPowerApiError(f"关闭 AdsPower 指纹环境失败: {last_error}")


def _attach_with_debugger_address(debug_port: str, webdriver_path: Optional[str] = None):
    options = webdriver.ChromeOptions()
    options.debugger_address = f"127.0.0.1:{debug_port}"
    if webdriver_path:
        service = Service(executable_path=webdriver_path)
        return webdriver.Chrome(service=service, options=options)
    return webdriver.Chrome(options=options)


def _ensure_attached_window_ready(driver):
    try:
        handles = driver.window_handles
    except NoSuchWindowException as exc:
        raise AdsPowerLaunchError("AdsPower 接管成功但浏览器窗口已关闭") from exc
    except WebDriverException as exc:
        raise AdsPowerLaunchError(f"AdsPower 接管成功但无法读取窗口句柄: {exc}") from exc

    if not handles:
        raise AdsPowerLaunchError("AdsPower 接管成功但没有可用浏览器窗口")

    try:
        driver.switch_to.window(handles[0])
    except NoSuchWindowException as exc:
        raise AdsPowerLaunchError("AdsPower 接管成功但首个浏览器窗口不可用") from exc
    except WebDriverException as exc:
        raise AdsPowerLaunchError(f"AdsPower 接管成功但切换窗口失败: {exc}") from exc

    try:
        driver.current_url
    except NoSuchWindowException as exc:
        raise AdsPowerLaunchError("AdsPower 接管成功但当前浏览器窗口已失效") from exc
    except WebDriverException as exc:
        raise AdsPowerLaunchError(f"AdsPower 接管成功但当前窗口状态异常: {exc}") from exc


def open_env_with_retry(env_id, max_retries=1, page_load_timeout=60):
    profile_id = str(env_id).strip()
    if not profile_id:
        raise AdsPowerLaunchError("缺少标准化后的 AdsPower profile_id")

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            debug_port = None
            remote_url = None
            webdriver_path = None

            try:
                _, debug_port, remote_url, webdriver_path = _start_profile_v2(profile_id)
            except AdsPowerApiError as exc:
                if _is_transient_startup_error(exc):
                    raise exc
                print(f"WARN: AdsPower v2 启动失败，尝试回退 v1: {exc}")
                _, debug_port, remote_url, webdriver_path = _start_profile_v1(profile_id)

            if debug_port:
                _wait_for_debug_port(debug_port)
                try:
                    if webdriver_path:
                        driver = _attach_with_debugger_address(debug_port, webdriver_path=webdriver_path)
                    else:
                        driver = _attach_with_debugger_address(debug_port)
                except WebDriverException as exc:
                    if webdriver_path:
                        print(f"WARN: AdsPower webdriver 接管失败，回退 Selenium Manager: {exc}")
                        driver = _attach_with_debugger_address(debug_port)
                    else:
                        raise exc
            elif remote_url:
                driver = webdriver.Remote(command_executor=remote_url)
            else:
                raise AdsPowerLaunchError("AdsPower 启动成功，但未返回可用的 debug_port 或 Remote WebDriver URL")

            _ensure_attached_window_ready(driver)
            driver.set_page_load_timeout(page_load_timeout)
            return driver
        except (AdsPowerError, WebDriverException) as exc:
            last_error = exc
            print(f"WARN: 第 {attempt}/{max_retries} 次启动或接管 AdsPower 失败: {exc}")
            if attempt < max_retries:
                time.sleep(5 if isinstance(exc, AdsPowerApiError) and _is_transient_startup_error(exc) else 1)

    raise AdsPowerLaunchError(f"无法启动或接管 AdsPower profile: {last_error}") from last_error


def set_fullscreen_mode(driver):
    try:
        driver.maximize_window()
    except Exception as exc:
        print(f"WARN: 最大化浏览器窗口失败: {exc}")
