#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rakuten Advertising Publisher 申请脚本。
打开指纹浏览器 -> 访问 Rakuten Advertising Publisher 页面 -> 自动登录
-> 按 subject_id + env_serial 读取 branlist -> 搜索品牌并申请
-> 记录 apply_window / apply_log。
"""

import argparse
import os
import random
import re
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR
sys.path.append(PROJECT_ROOT)

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from lib.env_manager import open_env_by_serial
from lib.fingerprint_utils import preload_fingerprint_cache, stop_env
from lib.google_sheets_helper import get_sheets_service
from lib.logger import setup_logger, close_logger
from lib.rakuten_auth import login_rakuten, is_login_page, is_logged_in
from lib.runtime_model import (
    APPLY_LOG_HEADERS,
    APPLY_LOG_RESULT,
    APPLY_LOG_SHEET,
    APPLY_STATUS_APPLIED,
    APPLY_STATUS_DISABLED,
    APPLY_STATUS_FAILED,
    APPLY_STATUS_PENDING,
    APPLY_STATUS_SKIPPED,
    APPLY_WINDOW_HEADERS,
    APPLY_WINDOW_SHEET,
    BRANLIST_HEADERS,
    BRANLIST_SHEET,
    TASK_STATUS_DISABLED,
    WINDOW_STATUS_ACTIVE,
    append_record,
    build_header_map,
    get_cell,
    get_runtime_spreadsheet_id,
    missing_headers,
    now_iso,
    read_sheet_with_headers,
    resolve_subject_credentials,
    update_sheet_row,
)
from lib.selenium_helpers import (
    find_el, find_el_clickable, click_el,
    wait_page_stable, wait_page_full_load,
    wait_until, safe_navigate,
)
from lib.selenium_input import fill_input_value

# =====================
# 常量配置
# =====================
RAKUTEN_URL = "https://publisher.rakutenadvertising.com/"
ADVERTISERS_SEARCH_URL = "https://publisher.rakutenadvertising.com/advertisers/search"

# 超时参数（秒）
PAGE_LOAD_TIMEOUT = 60
WAIT_FULL_LOAD = 30
SEARCH_RESULT_TIMEOUT = 35
SUBMIT_WAIT_TIMEOUT = 12
BRAND_INTERVAL = 3
SEARCH_MIN_WAIT = 8          # 搜索触发后最少等待
DIALOG_MIN_WAIT = 5          # 弹窗出现最少等待
TERMS_CLICK_SETTLE = 2       # 勾选条款后最少等待

def get_spreadsheet_id() -> str:
    return get_runtime_spreadsheet_id()


# =====================
# 通用工具
# =====================
def now_dt() -> datetime:
    return datetime.now().astimezone()




def parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


# 向后兼容别名（旧的下划线前缀名称）
_find_el = find_el
_find_el_clickable = find_el_clickable
_click_el = click_el
_wait_page_stable = wait_page_stable
_wait_page_full_load = wait_page_full_load
_is_login_page = is_login_page
_is_logged_in = is_logged_in


_ACCORDION_CSS_INJECTED: set = set()


def _disable_profile_accordion(driver) -> None:
    """CSS 注入方式禁用 Profile Accordion，每个页面只需执行一次。"""
    try:
        window_handle = driver.current_window_handle
    except Exception:
        window_handle = None
    if window_handle in _ACCORDION_CSS_INJECTED:
        return
    try:
        driver.execute_script(
            """
            if (document.getElementById('codex-accordion-blocker')) return;
            const style = document.createElement('style');
            style.id = 'codex-accordion-blocker';
            style.textContent = `
                #root > div > div:nth-child(2) > div:first-child {
                    pointer-events: none !important;
                    user-select: none !important;
                }
                #root > div > div:nth-child(2) > div:first-child summary,
                #root > div > div:nth-child(2) > div:first-child button,
                #root > div > div:nth-child(2) > div:first-child a,
                #root > div > div:nth-child(2) > div:first-child input,
                #root > div > div:nth-child(2) > div:first-child [role="button"],
                #root > div > div:nth-child(2) > div:first-child [tabindex] {
                    pointer-events: none !important;
                }
            `;
            document.head.appendChild(style);
            const blocked = document.evaluate("//*[@id='root']/div/div[2]/div[1]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (blocked && blocked.contains(document.activeElement)) document.activeElement.blur();
            """
        )
        if window_handle is not None:
            _ACCORDION_CSS_INJECTED.add(window_handle)
    except Exception:
        pass


def _js_click_element(driver, el, label: str = "element") -> bool:
    try:
        _disable_profile_accordion(driver)
        return bool(
            driver.execute_script(
                """
                const target = arguments[0];
                if (!target) return false;
                target.scrollIntoView({ block: 'center', inline: 'center' });
                for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                  target.dispatchEvent(new MouseEvent(type, {
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    buttons: type.endsWith('down') ? 1 : 0
                  }));
                }
                target.click();
                return true;
                """,
                el,
            )
        )
    except Exception as exc:
        print(f"WARN: JavaScript 点击 {label} 失败: {exc}")
        return False


def _is_displayed_enabled(el) -> bool:
    try:
        disabled = el.get_attribute("disabled")
        aria_disabled = (el.get_attribute("aria-disabled") or "").lower()
        return el.is_displayed() and el.is_enabled() and disabled is None and aria_disabled != "true"
    except Exception:
        return False


def _safe_text(el) -> str:
    try:
        text = el.text or ""
        if text.strip():
            return text.strip()
    except Exception:
        pass
    try:
        return (el.get_attribute("textContent") or "").strip()
    except Exception:
        return ""


def _normalize_offer_name(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _set_input_value(driver, input_el, value: str) -> bool:
    try:
        input_el.click()
        time.sleep(0.2)
        modifier = Keys.COMMAND if sys.platform == "darwin" else Keys.CONTROL
        ActionChains(driver).key_down(modifier).send_keys("a").key_up(modifier).send_keys(Keys.BACKSPACE).perform()
        time.sleep(0.2)
        input_el.send_keys(value)
        return True
    except Exception:
        pass

    try:
        driver.execute_script(
            """
            const el = arguments[0];
            const value = arguments[1];
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            el.focus();
            setter.call(el, '');
            el.dispatchEvent(new Event('input', { bubbles: true }));
            setter.call(el, value);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            input_el,
            value,
        )
        return True
    except Exception as e:
        print(f"WARN: 设置输入框失败: {e}")
        return False



# =====================
# Sheet 逻辑
# =====================
def read_branlist_data(service, subject_id: str, env_serial: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    headers, rows = read_sheet_with_headers(get_spreadsheet_id(), BRANLIST_SHEET, service)
    missing = missing_headers(headers, BRANLIST_HEADERS)
    if missing:
        print(f"ERROR: 工作表缺少表头: {missing}")
        return [], {}
    header_map = build_header_map(headers)

    brands = []
    for idx, row in enumerate(rows, start=2):
        row_subject = get_cell(row, header_map, "subject_id")
        row_env = get_cell(row, header_map, "env_serial")
        if row_subject != subject_id or row_env != str(env_serial):
            continue
        brand = get_cell(row, header_map, "brand")
        if not brand:
            continue
        brands.append(
            {
                "row_index": idx,
                "subject_id": row_subject,
                "env_serial": row_env,
                "category": get_cell(row, header_map, "category"),
                "brand": brand,
                "brand_url": get_cell(row, header_map, "brand_url"),
                "apply_status": get_cell(row, header_map, "apply_status"),
                "note": get_cell(row, header_map, "note"),
                "source_type": get_cell(row, header_map, "source_type"),
                "search_keyword": get_cell(row, header_map, "search_keyword"),
                "discovered_at": get_cell(row, header_map, "discovered_at"),
            }
        )

    print(f"INFO: 读取到 {len(brands)} 条 branlist 记录")
    return brands, header_map


def update_branlist_row(
    row_index: int,
    header_map: Dict[str, int],
    brand_url: str,
    apply_status: str,
    note: str,
    service=None,
):
    update_sheet_row(
        get_spreadsheet_id(),
        BRANLIST_SHEET,
        row_index,
        header_map,
        {
            "brand_url": brand_url,
            "apply_status": apply_status,
            "note": note,
        },
        service=service,
    )
    print(f"INFO: 更新 branlist 第 {row_index} 行状态='{apply_status}'")


def read_apply_windows(service, subject_id: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    headers, rows = read_sheet_with_headers(get_spreadsheet_id(), APPLY_WINDOW_SHEET, service)
    missing = missing_headers(headers, APPLY_WINDOW_HEADERS)
    if missing:
        print(f"ERROR: 工作表缺少表头: {missing}")
        return [], {}
    header_map = build_header_map(headers)

    windows = []
    for idx, row in enumerate(rows, start=2):
        row_subject = get_cell(row, header_map, "subject_id")
        row_env = get_cell(row, header_map, "env_serial")
        if row_subject != subject_id:
            continue
        windows.append(
            {
                "row_index": idx,
                "subject_id": row_subject,
                "env_serial": row_env,
                "window_start": get_cell(row, header_map, "window_start"),
                "window_end": get_cell(row, header_map, "window_end"),
                "limit": get_cell(row, header_map, "limit"),
                "status": get_cell(row, header_map, "status"),
            }
        )
    return windows, header_map


def append_apply_window(window_record: Dict[str, str], service=None):
    append_record(get_spreadsheet_id(), APPLY_WINDOW_SHEET, APPLY_WINDOW_HEADERS, window_record, service=service)
    print("INFO: 已创建新的 apply_window 记录")


def read_apply_logs(service, subject_id: str) -> List[Dict[str, str]]:
    headers, rows = read_sheet_with_headers(get_spreadsheet_id(), APPLY_LOG_SHEET, service)
    missing = missing_headers(headers, APPLY_LOG_HEADERS)
    if missing:
        print(f"ERROR: 工作表缺少表头: {missing}")
        return []
    header_map = build_header_map(headers)

    logs = []
    for row in rows:
        row_subject = get_cell(row, header_map, "subject_id")
        row_env = get_cell(row, header_map, "env_serial")
        if row_subject != subject_id:
            continue
        logs.append(
            {
                "subject_id": row_subject,
                "env_serial": row_env,
                "brand": get_cell(row, header_map, "brand"),
                "brand_url": get_cell(row, header_map, "brand_url"),
                "applied_at": get_cell(row, header_map, "applied_at"),
                "result": get_cell(row, header_map, "result"),
                "note": get_cell(row, header_map, "note"),
            }
        )
    return logs


def append_apply_log(record: Dict[str, str], service=None):
    append_record(get_spreadsheet_id(), APPLY_LOG_SHEET, APPLY_LOG_HEADERS, record, service=service)
    print(f"INFO: 已写入 apply_log: {record.get('brand')}")


def select_or_create_window(service, subject_id: str, env_serial: str) -> Dict[str, Any]:
    windows, _ = read_apply_windows(service, subject_id)
    candidates = []
    for window in windows:
        start_dt = parse_iso(window["window_start"])
        end_dt = parse_iso(window["window_end"])
        limit_text = window["limit"]
        if not start_dt or not end_dt or not limit_text:
            print(f"WARN: 忽略无效窗口数据: row={window['row_index']}")
            continue
        try:
            limit_value = int(limit_text)
        except ValueError:
            print(f"WARN: 忽略 limit 非法的窗口数据: row={window['row_index']}")
            continue
        candidates.append(
            {
                **window,
                "window_start_dt": start_dt,
                "window_end_dt": end_dt,
                "limit_value": limit_value,
            }
        )

    if candidates:
        candidates.sort(key=lambda item: item["window_start_dt"], reverse=True)
        active_candidates = [item for item in candidates if now_dt() < item["window_end_dt"]]
        if len(active_candidates) > 1:
            print(f"WARN: 检测到多个未过期窗口，使用最新窗口 row={active_candidates[0]['row_index']}")

        latest = candidates[0]
        if now_dt() < latest["window_end_dt"]:
            print(
                f"INFO: 复用现有窗口 start={latest['window_start']} end={latest['window_end']} limit={latest['limit_value']}"
            )
            return latest

    start_dt = now_dt()
    end_dt = start_dt + timedelta(hours=24)
    limit_value = random.randint(30, 40)
    record = {
        "subject_id": subject_id,
        "env_serial": str(env_serial),
        "window_start": start_dt.isoformat(timespec="seconds"),
        "window_end": end_dt.isoformat(timespec="seconds"),
        "limit": str(limit_value),
        "status": WINDOW_STATUS_ACTIVE,
    }
    append_apply_window(record, service=service)
    print(
        f"INFO: 创建新窗口 start={record['window_start']} end={record['window_end']} limit={limit_value}"
    )
    return {
        **record,
        "window_start_dt": start_dt,
        "window_end_dt": end_dt,
        "limit_value": limit_value,
    }


def count_used_slots(logs: List[Dict[str, str]], window: Dict[str, Any]) -> int:
    used = 0
    start_dt = window["window_start_dt"]
    end_dt = window["window_end_dt"]
    for log in logs:
        if log.get("result") != APPLY_LOG_RESULT:
            continue
        applied_at = parse_iso(log.get("applied_at", ""))
        if not applied_at:
            continue
        if start_dt <= applied_at < end_dt:
            used += 1
    return used


# =====================
# 申请逻辑
# =====================
def _find_offer_search_input(driver, timeout: int = 15):
    selectors = [
        (By.CSS_SELECTOR, "input.AdvancedSearchBar__input"),
        (By.CSS_SELECTOR, "input[data-cy*='search' i]"),
        (By.CSS_SELECTOR, "input[name*='search' i]"),
        (By.CSS_SELECTOR, "input[placeholder*='Search' i]"),
        (By.CSS_SELECTOR, "input[aria-label*='Search' i]"),
        (By.XPATH, "//input[contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'advertiser')]"),
        (By.XPATH, "//input[contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'search')]"),
    ]
    for by, loc in selectors:
        search_input = _find_el_clickable(driver, by, loc, timeout=timeout)
        if search_input:
            return search_input
    return None


def _trigger_offer_search(driver, search_input) -> bool:
    _disable_profile_accordion(driver)

    def submitted(before_url: str) -> bool:
        try:
            current_url = driver.current_url or ""
            if current_url != before_url and "/advertisers/find" in current_url:
                return True
            body_text = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
            return "showing" in body_text and "results for" in body_text
        except Exception:
            return False

    def click_search_button() -> bool:
        button_candidates = []
        try:
            clicked = driver.execute_script(
                """
                const input = arguments[0];
                const form = input.closest('form');
                if (!form) return false;
                const blocked = document.evaluate("//*[@id='root']/div/div[2]/div[1]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (blocked && blocked.contains(document.activeElement)) document.activeElement.blur();
                const button = form.querySelector("button.AdvancedSearchBar__button[aria-label='Search'], button[aria-label='Search'][type='submit'], button[type='submit']");
                if (!button) return false;

                button.scrollIntoView({ block: 'center', inline: 'center' });
                for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                  button.dispatchEvent(new MouseEvent(type, {
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    buttons: type.endsWith('down') ? 1 : 0
                  }));
                }
                button.click();
                if (form) {
                  if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit(button);
                  } else {
                    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                  }
                }
                return true;
                """,
                search_input,
            )
            if clicked:
                print("INFO: 已使用 JavaScript 点击搜索按钮")
                return True
        except Exception as exc:
            print(f"WARN: JavaScript 点击搜索按钮失败: {exc}")

        selectors = [
            (By.XPATH, "./ancestor::form[1]//button[@aria-label='Search' and @type='submit']"),
            (By.XPATH, "./ancestor::form[1]//button[contains(@class,'AdvancedSearchBar__button')]"),
        ]
        for by, loc in selectors:
            try:
                button_candidates.extend(search_input.find_elements(by, loc))
            except Exception:
                continue

        seen = set()
        for btn in button_candidates:
            try:
                if btn.id in seen:
                    continue
                seen.add(btn.id)
                if _is_displayed_enabled(btn) and _click_el(driver, btn):
                    return True
            except Exception:
                continue
        return False

    before_url = driver.current_url or ""
    enter_sent = False
    try:
        driver.execute_script(
            """
            const input = arguments[0];
            const blocked = document.evaluate("//*[@id='root']/div/div[2]/div[1]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (blocked && blocked.contains(document.activeElement)) document.activeElement.blur();
            input.scrollIntoView({block:'center', inline:'center'});
            input.focus();
            """,
            search_input,
        )
        search_input.click()
        time.sleep(0.2)
        focused = driver.execute_script(
            """
            const input = arguments[0];
            const blocked = document.evaluate("//*[@id='root']/div/div[2]/div[1]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            return document.activeElement === input && !(blocked && blocked.contains(document.activeElement));
            """,
            search_input,
        )
        if focused:
            print("INFO: 搜索框已获得焦点，按 Enter 提交搜索...")
            search_input.send_keys(Keys.ENTER)
            enter_sent = True
        else:
            active_desc = driver.execute_script(
                "const el = document.activeElement; return el ? `${el.tagName}#${el.id || ''}.${el.className || ''}` : '';"
            )
            print(f"WARN: 搜索框未获得焦点，当前焦点在 {active_desc}，跳过 Enter")
    except Exception:
        print("WARN: 搜索框聚焦失败，跳过 Enter，改用搜索按钮")

    if enter_sent:
        end = time.time() + 2
        while time.time() < end:
            if submitted(before_url):
                return True
            time.sleep(0.3)

    print("WARN: 回车未触发搜索，改为点击搜索按钮...")
    if click_search_button():
        end = time.time() + 5
        while time.time() < end:
            if submitted(before_url):
                return True
            time.sleep(0.3)
        return True

    return False


def _get_offer_cards(driver) -> List[Any]:
    selectors = [
        "div[class*='CardWrapper']",
        "div[data-cy*='advertiser' i]",
        "div[data-testid*='advertiser' i]",
        "article",
        "li[class*='Card' i]",
        "div[class*='Advertiser' i][class*='Card' i]",
    ]
    seen = set()
    cards = []
    for selector in selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, selector):
                try:
                    if not el.is_displayed():
                        continue
                    key = el.id
                    text = _safe_text(el)
                    if key in seen or len(text) < 2:
                        continue
                    seen.add(key)
                    cards.append(el)
                except Exception:
                    continue
        except Exception:
            continue
    return cards


def _extract_offer_card_name(card) -> str:
    selectors = [
        "div.Truncated",
        "div[class*='Truncated']",
        "a[href*='/advertisers/']",
        "h2",
        "h3",
        "[class*='Name']",
        "[class*='Title']",
    ]
    candidates = []
    for selector in selectors:
        try:
            for el in card.find_elements(By.CSS_SELECTOR, selector):
                text = _safe_text(el)
                if text and len(text) <= 120:
                    candidates.append(text)
        except Exception:
            continue

    if candidates:
        return candidates[0].strip()

    lines = [line.strip() for line in _safe_text(card).splitlines() if line.strip()]
    return lines[0] if lines else ""


def _offer_match_score(brand: str, card_name: str, card_text: str) -> int:
    brand_norm = _normalize_offer_name(brand)
    name_norm = _normalize_offer_name(card_name)
    text_norm = _normalize_offer_name(card_text)
    if not brand_norm:
        return 0

    if name_norm == brand_norm:
        return 100
    if name_norm and (name_norm.startswith(brand_norm) or brand_norm.startswith(name_norm)):
        return 88
    if re.search(rf"\b{re.escape(brand_norm)}\b", text_norm):
        return 75

    brand_tokens = set(brand_norm.split())
    name_tokens = set(name_norm.split())
    if brand_tokens and name_tokens:
        overlap = len(brand_tokens & name_tokens) / max(len(brand_tokens), len(name_tokens))
        if overlap >= 0.75:
            return 65
    return 0


def _find_best_offer_card(driver, brand: str) -> Tuple[Optional[Any], List[str], int]:
    cards = _get_offer_cards(driver)
    titles = []
    best_card = None
    best_score = 0
    non_offer_titles = {"find advertisers", "see all advertisers"}
    for card in cards:
        card_name = _extract_offer_card_name(card)
        card_text = _safe_text(card)
        if _normalize_offer_name(card_name) in non_offer_titles:
            continue
        if card_name:
            titles.append(card_name)
        score = _offer_match_score(brand, card_name, card_text)
        if score > best_score:
            best_card = card
            best_score = score
    return best_card, titles, best_score


def _wait_for_offer_results(driver, brand: str, timeout: int = 35, min_wait: float = 0) -> Tuple[List[Any], bool]:
    """等待搜索结果加载并稳定。
    - min_wait: 最少等待秒数（即使卡片出现也要等够，给网络时间渲染内容）
    - 只有卡片数量稳定且卡片内容非空时才认为结果就绪
    """
    print(f"INFO: 等待 '{brand}' 搜索结果加载...")
    start = time.time()
    last_count = -1
    stable_rounds = 0
    no_result_keywords = [
        "no results",
        "no advertisers",
        "couldn't find",
        "did not match",
        "没有结果",
        "未找到",
    ]

    while time.time() - start < timeout:
        elapsed = time.time() - start
        cards = _get_offer_cards(driver)
        if cards:
            # 检查卡片是否有实际文字内容（防止骨架屏/占位符卡片）
            has_content = any(
                len((_safe_text(card) or "").strip()) > 10
                for card in cards
            )
            count = len(cards)
            if count == last_count and has_content:
                stable_rounds += 1
            else:
                stable_rounds = 0
            last_count = count
            # 只有稳定且过了最低等待时间才返回
            if stable_rounds >= 2 and elapsed >= min_wait:
                print(f"INFO: 搜索结果稳定，当前 {count} 个候选卡片 (耗时 {elapsed:.1f}秒)")
                return cards, False

        # 过了最低等待时间后才检查“无结果”
        if elapsed >= min_wait:
            try:
                body_text = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
                if any(kw in body_text for kw in no_result_keywords):
                    return [], True
            except Exception:
                pass

        time.sleep(1)

    cards = _get_offer_cards(driver)
    return cards, False


def _open_offer_from_card(driver, card) -> bool:
    _disable_profile_accordion(driver)
    before_url = driver.current_url
    href = None

    try:
        click_result = driver.execute_script(
            """
            const card = arguments[0];
            const candidates = Array.from(card.querySelectorAll("button, a, [role='button']"));
            const target = candidates.find((el) => {
              const text = (el.innerText || el.textContent || "").trim().toLowerCase();
              const rect = el.getBoundingClientRect();
              const style = window.getComputedStyle(el);
              return text.includes("view offer")
                && rect.width > 0
                && rect.height > 0
                && style.visibility !== "hidden"
                && style.display !== "none"
                && !el.disabled
                && el.getAttribute("aria-disabled") !== "true";
            });
            if (!target) {
              const link = card.querySelector("a[href*='/advertisers/']");
              return { clicked: false, href: link ? link.href : null, text: "" };
            }

            target.scrollIntoView({ block: "center", inline: "center" });
            const text = (target.innerText || target.textContent || "").trim();
            for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
              target.dispatchEvent(new MouseEvent(type, {
                bubbles: true,
                cancelable: true,
                view: window,
                buttons: type.endsWith("down") ? 1 : 0
              }));
            }
            target.click();
            return { clicked: true, href: target.href || null, text };
            """,
            card,
        )
        if click_result and click_result.get("clicked"):
            print(f"INFO: 已使用 JavaScript 点击 View offer: '{(click_result.get('text') or '')[:80]}'")
        if click_result and click_result.get("href"):
            href = click_result.get("href")
    except Exception as exc:
        print(f"WARN: JavaScript 点击 View offer 失败: {exc}")

    if not href:
        try:
            href = driver.execute_script(
                "const link = arguments[0].querySelector(\"a[href*='/advertisers/']\"); return link ? link.href : null;",
                card,
            )
        except Exception:
            href = None

    if href:
        print(f"INFO: 如点击未跳转，将使用详情链接兜底: {href[:100]}")

    end = time.time() + 25
    while time.time() < end:
        try:
            current_url = driver.current_url
            body_text = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
            if current_url != before_url and "/advertisers" in current_url:
                return True
            if "apply" in body_text and ("commission" in body_text or "partnership" in body_text):
                return True
        except Exception:
            pass
        time.sleep(1)
    if driver.current_url != before_url:
        return True
    if href:
        driver.get(href)
        _wait_page_full_load(driver, timeout=30)
        return driver.current_url != before_url
    return False


def _find_first_enabled_button_by_text(driver, labels: List[str], timeout: int = 10):
    deadline = time.time() + timeout
    lowered = [label.lower() for label in labels]
    while time.time() < deadline:
        try:
            buttons = driver.find_elements(By.XPATH, "//button | //a[@role='button'] | //*[@role='button']")
            for btn in buttons:
                text = _safe_text(btn).lower()
                if any(label in text for label in lowered) and _is_displayed_enabled(btn):
                    return btn
        except Exception:
            pass
        time.sleep(0.8)
    return None


def is_pending_approval_card(card) -> bool:
    try:
        return "partnership pending approval" in (card.text or "").lower()
    except Exception:
        return False


def is_partnered_text(value: str) -> bool:
    text = (value or "").lower()
    return "partnered" in text and "not partnered" not in text


def is_partnered_card(card) -> bool:
    try:
        return is_partnered_text(card.text or "")
    except Exception:
        return False


def get_page_text(driver) -> str:
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        return body.text or ""
    except Exception:
        return ""


def is_partnered_page(driver) -> bool:
    return is_partnered_text(get_page_text(driver))


def is_pending_approval_page(driver) -> bool:
    page_text = get_page_text(driver).lower()
    return "partnership pending approval" in page_text or "pending approval" in page_text


def process_brand_application(driver, brand_info: Dict[str, Any], service=None, header_map=None) -> bool:
    brand = brand_info["brand"]
    row_idx = brand_info["row_index"]

    print(f"\n{'─' * 50}")
    print(f"  处理品牌申请: {brand} (行号 {row_idx})")
    print(f"{'─' * 50}")

    try:
        # 打开搜索页（带重试）
        print(f"INFO: 导航到搜索页面: {ADVERTISERS_SEARCH_URL}")
        _ACCORDION_CSS_INJECTED.discard(driver.current_window_handle if hasattr(driver, 'current_window_handle') else None)
        if not safe_navigate(driver, ADVERTISERS_SEARCH_URL, timeout=WAIT_FULL_LOAD):
            print("ERROR: 搜索页面加载失败")
            return False

        # 输入品牌搜索
        _disable_profile_accordion(driver)
        print("INFO: 查找搜索框...")
        search_input = _find_offer_search_input(driver, timeout=15)
        if not search_input:
            print("ERROR: 未找到搜索框")
            return False

        if not _set_input_value(driver, search_input, brand):
            print("ERROR: 搜索词输入失败")
            return False
        time.sleep(1)

        # 点击搜索按钮
        _disable_profile_accordion(driver)
        print("INFO: 点击搜索...")
        if not _trigger_offer_search(driver, search_input):
            print("ERROR: 无法触发搜索")
            return False

        # 智能等待搜索结果（最少等 SEARCH_MIN_WAIT 秒保证网络加载）
        print("INFO: 搜索已触发，等待结果渲染...")
        cards, no_result = _wait_for_offer_results(driver, brand, timeout=SEARCH_RESULT_TIMEOUT, min_wait=SEARCH_MIN_WAIT)

        # 查找匹配的品牌卡片
        print("INFO: 匹配结果...")
        if no_result or not cards:
            print(f"INFO: 分类 '{brand}' 没有结果")
            update_branlist_row(row_idx, header_map, "", APPLY_STATUS_SKIPPED, "没有找到该offer", service)
            return False

        matched_card, current_titles, match_score = _find_best_offer_card(driver, brand)
        if not matched_card or match_score < 65:
            print(f"INFO: 没有找到足够匹配 '{brand}' 的结果 (score={match_score}, 结果有: {current_titles[:10]})")
            update_branlist_row(row_idx, header_map, "", APPLY_STATUS_SKIPPED, "没有找到该offer", service)
            return False

        print(f"INFO: 找到匹配品牌卡片 (score={match_score})，准备进入 offer 详情...")
        if not _open_offer_from_card(driver, matched_card):
            print("WARN: 第一次点击结果未进入详情页，重新获取结果后再试一次...")
            matched_card, current_titles, match_score = _find_best_offer_card(driver, brand)
            if not matched_card or not _open_offer_from_card(driver, matched_card):
                print(f"ERROR: 无法点击进入 '{brand}' 的 offer 详情")
                update_branlist_row(row_idx, header_map, "", APPLY_STATUS_FAILED, "搜索结果点击失败", service)
                return False

        # 等待详情页面
        _wait_page_full_load(driver, timeout=WAIT_FULL_LOAD)
        current_url = driver.current_url
        print(f"INFO: 进入详情页: {current_url[:80]}")

        # 查找 Apply 按钮
        _disable_profile_accordion(driver)
        apply_btn = None
        for by, loc in [
            (By.CSS_SELECTOR, "button[data-cy='partnership-apply-btn']"),
            (By.XPATH, "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'apply')]"),
        ]:
            apply_btn = _find_el_clickable(driver, by, loc, timeout=8)
            if apply_btn:
                break

        if not apply_btn:
            apply_btn = _find_first_enabled_button_by_text(driver, ["Apply", "Request Partnership"], timeout=5)

        if not apply_btn:
            body_text = ""
            try:
                body_text = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
            except Exception:
                pass
            already_applied = any(kw in body_text for kw in ["pending", "applied", "approved", "active", "partnered"])
            if already_applied:
                print("INFO: 页面显示已申请/已合作状态")
                update_branlist_row(row_idx, header_map, current_url, APPLY_STATUS_APPLIED, "页面已存在合作或申请状态", service)
            else:
                print("INFO: 没有找到 Apply 按钮 (可能不支持申请或已申请过)")
                update_branlist_row(row_idx, header_map, current_url, APPLY_STATUS_SKIPPED, "没有Apply按钮", service)
            brand_info["brand_url"] = current_url
            return already_applied

        print("INFO: 点击 Apply...")
        _disable_profile_accordion(driver)
        if not _js_click_element(driver, apply_btn, "Apply"):
            print("ERROR: Apply 按钮点击失败")
            update_branlist_row(row_idx, header_map, current_url, APPLY_STATUS_FAILED, "Apply按钮点击失败", service)
            return False

        # 智能等待弹窗出现（最少等 DIALOG_MIN_WAIT 秒）
        print("INFO: 已点击 Apply，等待申请弹窗加载...")
        wait_until(
            driver,
            lambda: driver.find_elements(By.CSS_SELECTOR, "[role='dialog'], body > div:not(#root) button"),
            timeout=10, min_wait=DIALOG_MIN_WAIT, description="Apply dialog",
        )

        print("INFO: 开始关注弹窗状态及 Send Request 按钮...")
        start_wait = time.time()
        send_btn_ready = None
        click_count = 0

        while time.time() - start_wait < 30:
            # 定位 Send Request 按钮
            current_send_btn = None
            try:
                current_send_btn = driver.execute_script(
                    """
                    const candidates = Array.from(document.querySelectorAll("body > div button, [role='dialog'] button, button"));
                    return candidates.find((btn) => {
                      const text = (btn.innerText || btn.textContent || "").trim().toLowerCase();
                      const rect = btn.getBoundingClientRect();
                      const style = window.getComputedStyle(btn);
                      return text.includes("send request")
                        && rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden";
                    }) || null;
                    """
                )
            except Exception:
                pass

            if current_send_btn and _is_displayed_enabled(current_send_btn):
                print("INFO: Send Request 已变为可用状态！")
                send_btn_ready = current_send_btn
                break

            # 按钮不可用，寻找 Terms 并点击
            checkbox_label = None
            try:
                checkbox_label = driver.execute_script(
                    """
                    const labels = Array.from(document.querySelectorAll("body > div label, [role='dialog'] label, label"));
                    return labels.find((label) => {
                      const text = (label.innerText || label.textContent || "").trim().toLowerCase();
                      const rect = label.getBoundingClientRect();
                      const style = window.getComputedStyle(label);
                      return (text.includes("accept terms") || text.includes("terms and conditions"))
                        && rect.width > 0
                        && rect.height > 0
                        && style.display !== "none"
                        && style.visibility !== "hidden";
                    }) || null;
                    """
                )
            except Exception:
                checkbox_label = None

            if not checkbox_label:
                for by, loc in [
                    (By.XPATH, "/html/body/div[11]/div/div[1]/div[1]/div/div[1]/div[3]/label"),
                    (By.CSS_SELECTOR, "label[for^='Checkbox-']"),
                    (By.XPATH, "//label[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept terms')]"),
                    (By.XPATH, "//label[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'terms and conditions')]"),
                    (By.CSS_SELECTOR, "label[class*='Checkbox']"),
                    (By.CSS_SELECTOR, "input[type='checkbox']"),
                ]:
                    try:
                        labels = driver.find_elements(by, loc)
                        for label in labels:
                            if label.is_displayed():
                                checkbox_label = label
                                break
                        if checkbox_label:
                            break
                    except Exception:
                        pass

            if checkbox_label:
                click_count += 1
                if click_count == 1:
                    print("INFO: 正在首次勾选 Accept Terms 勾选框...")
                else:
                    print(f"INFO: 当前 Send Request 仍不可点击，再次尝试勾选 Accept Terms (第{click_count}次)...")

                _disable_profile_accordion(driver)
                try:
                    checked = driver.execute_script(
                        """
                        const label = arguments[0];
                        const id = label.getAttribute('for');
                        const input = id ? document.getElementById(id) : label.querySelector("input[type='checkbox']");
                        const target = input || label;
                        target.scrollIntoView({ block: 'center', inline: 'center' });
                        for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                          target.dispatchEvent(new MouseEvent(type, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            buttons: type.endsWith('down') ? 1 : 0
                          }));
                        }
                        target.click();
                        label.click();
                        return input ? input.checked : true;
                        """,
                        checkbox_label,
                    )
                    print(f"INFO: Accept Terms 点击完成，checked={checked}")
                except Exception:
                    _js_click_element(driver, checkbox_label, "Accept Terms")
                # 智能等待 Send Request 变为可点击（最少等 TERMS_CLICK_SETTLE 秒防暂击）
                wait_until(
                    driver,
                    lambda: current_send_btn and _is_displayed_enabled(current_send_btn),
                    timeout=5, min_wait=TERMS_CLICK_SETTLE, description="Send Request enabled",
                )
            else:
                time.sleep(1)

        if send_btn_ready:
            print("INFO: 发送申请请求...")
            _disable_profile_accordion(driver)
            if not _js_click_element(driver, send_btn_ready, "Send Request"):
                try:
                    send_btn_ready = driver.find_element(By.XPATH, "/html/body/div[11]/div/div[1]/div[1]/div/div[1]/div[3]/div/button[2]")
                except Exception:
                    pass
            if not _js_click_element(driver, send_btn_ready, "Send Request"):
                print("ERROR: Send Request 点击失败")
                update_branlist_row(row_idx, header_map, current_url, APPLY_STATUS_FAILED, "Send Request点击失败", service)
                return False
        else:
            print("ERROR: Send Request 按钮在多次尝试后未能变为可用状态")
            update_branlist_row(row_idx, header_map, current_url, APPLY_STATUS_FAILED, "Send Request未能可用", service)
            return False

        # 智能等待弹窗关闭（最少 3 秒，最多 SUBMIT_WAIT_TIMEOUT 秒）
        print("INFO: 等待提交完成...")
        wait_until(
            driver,
            lambda: not driver.find_elements(By.CSS_SELECTOR, "[role='dialog']:not([aria-hidden='true'])"),
            timeout=SUBMIT_WAIT_TIMEOUT, min_wait=3, description="dialog close",
        )

        # 刷新页面验证
        print("INFO: 刷新页面验证状态...")
        driver.refresh()
        _wait_page_full_load(driver, timeout=WAIT_FULL_LOAD)

        # 检查 Pending (applied)
        pending_tag = _find_el(
            driver,
            By.XPATH,
            "//div[contains(@class, 'PartnershipPendingTag')]//p[contains(text(), 'Pending')]",
            timeout=10,
        )
        if pending_tag:
            print("✅ 状态验证通过: Pending (applied)")
            update_branlist_row(row_idx, header_map, current_url, APPLY_STATUS_APPLIED, "Pending (applied)", service)
            brand_info["brand_url"] = current_url
            return True
        else:
            print("WARN: 状态验证失败，未检测到 Pending 标签")
            update_branlist_row(row_idx, header_map, current_url, APPLY_STATUS_FAILED, "提交后未见Pending状态", service)
            brand_info["brand_url"] = current_url
        return False

    except Exception as e:
        print(f"ERROR: 处理品牌 '{brand}' 失败: {e}")
        traceback.print_exc()
        return False




# =====================
# 主流程
# =====================
def process(subject_id: str, env_serial: str, email: str = None, password: str = None, limit: int = None, close_on_finish: bool = False) -> bool:
    driver, env_id = open_env_by_serial(env_serial)
    if not driver:
        print(f"ERROR: 指纹环境启动失败 (序号: {env_serial})")
        return False

    try:
        print(f"\n{'=' * 55}")
        print("  Rakuten Advertising Publisher 申请")
        print(f"  subject_id: {subject_id}")
        print(f"  env_serial: {env_serial}")
        print(f"{'=' * 55}")

        service = get_sheets_service()
        if not service:
            print("ERROR: 无法初始化 Google Sheets 服务")
            return False

        print(f"\nINFO: 正在访问 {RAKUTEN_URL}")
        if not safe_navigate(driver, RAKUTEN_URL, timeout=PAGE_LOAD_TIMEOUT):
            print("ERROR: 无法访问 Rakuten 首页")
            return False
        print(f"INFO: 页面加载完成，当前 URL: {driver.current_url[:80]}")

        if not login_rakuten(driver, email=email, password=password):
            print("ERROR: 登录失败")
            return False

        brands_data, branlist_header_map = read_branlist_data(service, subject_id, env_serial)
        if not brands_data:
            print("ERROR: 当前主体没有 branlist 数据")
            return False

        pending_brands = [
            brand
            for brand in brands_data
            if (not brand["apply_status"] or brand["apply_status"] == APPLY_STATUS_PENDING)
            and brand["apply_status"] != APPLY_STATUS_DISABLED
        ]
        print(f"INFO: 当前主体待申请品牌数: {len(pending_brands)}")
        if not pending_brands:
            print("INFO: 没有待申请品牌")
            return True

        window = select_or_create_window(service, subject_id, env_serial)
        logs = read_apply_logs(service, subject_id)
        used_count = count_used_slots(logs, window)
        success_remaining = max(window["limit_value"] - used_count, 0)
        print(f"INFO: 当前窗口额度 limit={window['limit_value']} used={used_count} remaining={success_remaining}")

        if success_remaining <= 0:
            print("INFO: 当前窗口额度已用尽，不再继续申请")
            return True

        process_limit = len(pending_brands) if limit is None else max(limit, 0)
        if limit is not None:
            print(f"INFO: 应用命令行限制后，本次最多处理 {process_limit} 个品牌")
        if process_limit <= 0:
            print("INFO: 本次处理数量上限为 0，不再继续申请")
            return True

        processed_count = 0
        processed_success = 0
        for idx, brand_info in enumerate(pending_brands, start=1):
            if processed_count >= process_limit:
                print(f"INFO: 已达到本次处理上限 {process_limit}，停止执行")
                break
            if processed_success >= success_remaining:
                print(f"INFO: 已达到窗口成功申请上限 {success_remaining}，停止执行")
                break

            print(f"\n{'=' * 55}")
            print(f"  进度: {idx}/{len(pending_brands)}")
            print(f"{'=' * 55}")

            processed_count += 1
            success = process_brand_application(
                driver,
                brand_info,
                service=service,
                header_map=branlist_header_map,
            )
            if success:
                append_apply_log(
                    {
                        "subject_id": subject_id,
                        "env_serial": str(env_serial),
                        "brand": brand_info["brand"],
                        "brand_url": brand_info["brand_url"],
                        "applied_at": now_iso(),
                        "result": APPLY_LOG_RESULT,
                        "note": "Pending (applied)",
                    },
                    service=service,
                )
                processed_success += 1

            time.sleep(BRAND_INTERVAL)

        print(f"\n{'=' * 55}")
        print("  申请完成!")
        print(f"  总待申请数: {len(pending_brands)}")
        print(f"  本次处理品牌: {processed_count}")
        print(f"  本次成功申请: {processed_success}")
        print(f"{'=' * 55}")
        return True
    except KeyboardInterrupt:
        print(f"\nINFO: 用户中断执行 (Ctrl+C)")
        print(f"INFO: 已处理 {processed_count} 个品牌，成功 {processed_success} 个")
        return False
    except Exception as e:
        print(f"ERROR: 处理过程异常: {e}")
        traceback.print_exc()
        return False
    finally:
        if close_on_finish:
            try:
                driver.quit()
            except Exception as exc:
                print(f"WARN: 关闭 Selenium driver 失败: {exc}")
            try:
                stop_env(env_id)
            except Exception as exc:
                print(f"WARN: 关闭 AdsPower 指纹环境失败: {exc}")
            else:
                print(f"INFO: 指纹环境 {env_id} 已关闭")
        else:
            print(f"INFO: 指纹环境 {env_id} 保持打开状态")


def main():
    # 初始化日志系统（必须在所有业务逻辑之前）
    setup_logger("rakuten_aff_apply")

    parser = argparse.ArgumentParser(description="Rakuten Advertising Publisher 申请脚本")
    parser.add_argument("--subject-id", type=str, default=None, help="运行主体 ID，默认等于 --env-serial")
    parser.add_argument("--env-serial", "-s", type=str, required=True, help="AdsPower 指纹id")
    parser.add_argument("--email", "-e", type=str, default=None, help="登录邮箱，默认从 King 读取")
    parser.add_argument("--password", "-p", type=str, default=None, help="登录密码，默认从 King 读取")
    parser.add_argument("-n", "--num", type=int, default=None, help="本次执行处理的品牌数量上限")
    parser.add_argument("--close-on-finish", action="store_true", help="执行完成后关闭 AdsPower 浏览器")
    args = parser.parse_args()
    subject_id = args.subject_id or args.env_serial
    email = args.email
    password = args.password
    if not email or not password:
        email, password, resolved_env = resolve_subject_credentials(get_spreadsheet_id(), get_sheets_service(), subject_id)
        if not args.subject_id and resolved_env != args.env_serial:
            print(f"WARN: King 中主体当前绑定指纹id为 {resolved_env}，本次仍按命令行 env_serial={args.env_serial} 执行")

    print("INFO: 正在预加载指纹缓存...")
    preload_fingerprint_cache()

    try:
        success = process(
            subject_id=subject_id,
            env_serial=args.env_serial,
            email=email,
            password=password,
            limit=args.num,
            close_on_finish=args.close_on_finish,
        )

        if success:
            print("\n🎉 脚本执行完成")
        else:
            print("\n❌ 脚本执行失败")
            sys.exit(1)
    finally:
        close_logger()


if __name__ == "__main__":
    main()
