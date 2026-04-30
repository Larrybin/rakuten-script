#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rakuten Advertising Publisher 采集脚本。
打开指纹浏览器 -> 访问 Rakuten Advertising Publisher 页面 -> 自动登录
-> 按 subject_id + env_serial 读取 caturl / keywords
-> 采集品牌 -> 写入 branlist。
"""

import argparse
import os
import re
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR
sys.path.append(PROJECT_ROOT)

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from lib.env_manager import open_env_by_serial
from lib.fingerprint_utils import preload_fingerprint_cache, stop_env
from lib.google_sheets_helper import append_rows_to_sheet, get_sheets_service
from lib.logger import setup_logger, close_logger
from lib.rakuten_auth import login_rakuten, is_login_page, is_logged_in
from lib.runtime_model import (
    APPLY_STATUS_PENDING,
    BRANLIST_HEADERS,
    BRANLIST_SHEET,
    CATURL_HEADERS,
    CATURL_SHEET,
    KEYWORDS_HEADERS,
    KEYWORDS_SHEET,
    TASK_STATUS_DISABLED,
    TASK_STATUS_DONE,
    TASK_STATUS_FAILED,
    TASK_STATUS_PARTIAL,
    append_record,
    build_header_map,
    get_cell,
    get_runtime_spreadsheet_id,
    missing_headers,
    normalize_subject_id,
    now_iso,
    read_rows_as_records,
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
SOURCE_CATEGORY = "category_listing"
SOURCE_KEYWORD = "keyword_search"

# 超时参数（秒）
PAGE_LOAD_TIMEOUT = 60
WAIT_FULL_LOAD = 30
TASK_INTERVAL = 2


def get_spreadsheet_id() -> str:
    return get_runtime_spreadsheet_id()


def normalize_brand(brand: str) -> str:
    return (brand or "").strip().lower()


# 向后兼容别名（旧的下划线前缀名称）
_find_el = find_el
_find_el_clickable = find_el_clickable
_click_el = click_el
_wait_page_stable = wait_page_stable
_wait_page_full_load = wait_page_full_load
_is_login_page = is_login_page
_is_logged_in = is_logged_in


# =====================
# Sheet 数据读取
# =====================
def read_caturl_tasks(service, subject_id: str, env_serial: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    headers, rows = read_sheet_with_headers(get_spreadsheet_id(), CATURL_SHEET, service)
    missing = missing_headers(headers, CATURL_HEADERS)
    if missing:
        print(f"ERROR: 工作表缺少表头: {missing}")
        return [], {}
    header_map = build_header_map(headers)

    tasks = []
    for idx, row in enumerate(rows, start=2):
        row_subject = get_cell(row, header_map, "subject_id")
        row_env = get_cell(row, header_map, "env_serial")
        if row_subject != subject_id or row_env != str(env_serial):
            continue
        category = get_cell(row, header_map, "category")
        url = get_cell(row, header_map, "url")
        if not category or not url:
            continue
        tasks.append(
            {
                "row_index": idx,
                "subject_id": row_subject,
                "env_serial": row_env,
                "category": category,
                "url": url,
                "count": get_cell(row, header_map, "count"),
                "status": get_cell(row, header_map, "status"),
                "last_crawled_at": get_cell(row, header_map, "last_crawled_at"),
                "note": get_cell(row, header_map, "note"),
            }
        )

    print(f"INFO: 读取到 {len(tasks)} 条 caturl 任务")
    return tasks, header_map


def read_keyword_tasks(service, subject_id: str, env_serial: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    headers, rows = read_sheet_with_headers(get_spreadsheet_id(), KEYWORDS_SHEET, service)
    missing = missing_headers(headers, KEYWORDS_HEADERS)
    if missing:
        print(f"ERROR: 工作表缺少表头: {missing}")
        return [], {}
    header_map = build_header_map(headers)

    tasks = []
    for idx, row in enumerate(rows, start=2):
        row_subject = get_cell(row, header_map, "subject_id")
        row_env = get_cell(row, header_map, "env_serial")
        if row_subject != subject_id or row_env != str(env_serial):
            continue
        keyword = get_cell(row, header_map, "keyword")
        if not keyword:
            continue
        tasks.append(
            {
                "row_index": idx,
                "subject_id": row_subject,
                "env_serial": row_env,
                "keyword": keyword,
                "status": get_cell(row, header_map, "status"),
                "last_crawled_at": get_cell(row, header_map, "last_crawled_at"),
                "note": get_cell(row, header_map, "note"),
            }
        )

    print(f"INFO: 读取到 {len(tasks)} 条 keywords 任务")
    return tasks, header_map


def read_existing_brands(service, subject_id: str) -> Tuple[set, Dict[str, int]]:
    headers, rows = read_sheet_with_headers(get_spreadsheet_id(), BRANLIST_SHEET, service)
    missing = missing_headers(headers, BRANLIST_HEADERS)
    if missing:
        print(f"ERROR: 工作表缺少表头: {missing}")
        return set(), {}
    header_map = build_header_map(headers)

    brands = set()
    for row in rows:
        if get_cell(row, header_map, "subject_id") != subject_id:
            continue
        brand = normalize_brand(get_cell(row, header_map, "brand"))
        if brand:
            brands.add(brand)
    print(f"INFO: 当前主体已有 {len(brands)} 个品牌")
    return brands, header_map


def append_branlist_records(records: List[Dict[str, str]], service=None):
    if not records:
        return
    rows = [[record.get(header, "") for header in BRANLIST_HEADERS] for record in records]
    batch_size = 100
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        append_rows_to_sheet(batch, get_spreadsheet_id(), BRANLIST_SHEET, service_obj=service)
        if start + batch_size < len(rows):
            time.sleep(1)
    print(f"INFO: 已向 branlist 追加 {len(records)} 条记录")


# =====================
# 页面抓取逻辑
# =====================
def get_total_brand_count(driver) -> int:
    try:
        text = driver.execute_script(
            """
            var els = document.querySelectorAll('p.Text, p[class*="Text"]');
            for (var i = 0; i < els.length; i++) {
                var t = els[i].textContent || '';
                if (t.indexOf('results') !== -1 && t.indexOf('of') !== -1) {
                    return t.trim();
                }
            }
            return '';
            """
        ) or ""
        if text:
            print(f"INFO: 品牌统计文本: {text}")
            match = re.search(r"of\s+(\d[\d,]*)", text)
            if match:
                return int(match.group(1).replace(",", ""))

        page_source = driver.page_source
        match = re.search(r"Showing\s+\d+\s+of\s+(\d[\d,]*)\s+results", page_source)
        if match:
            return int(match.group(1).replace(",", ""))
    except Exception as e:
        print(f"WARN: 获取品牌总数失败: {e}")
    return 0


def has_search_result_cards(driver) -> bool:
    try:
        return bool(driver.find_elements(By.CSS_SELECTOR, "div[class*='CardWrapper']"))
    except Exception:
        return False


def has_no_search_results(driver) -> bool:
    if has_search_result_cards(driver):
        return False
    try:
        body_text = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
    except Exception:
        return False
    return any(
        phrase in body_text
        for phrase in [
            "no results found",
            "no matching results",
            "no advertisers found",
            "we couldn't find any results",
        ]
    )


def wait_for_search_results_ready(driver, timeout: int = 20) -> Tuple[str, int]:
    deadline = time.time() + timeout
    last_total_count = 0
    while time.time() < deadline:
        total_count = get_total_brand_count(driver)
        if total_count > 0 or has_search_result_cards(driver):
            return "results", total_count
        if has_no_search_results(driver):
            return "empty", 0
        time.sleep(1)
        last_total_count = total_count
    return "timeout", last_total_count


def load_all_brands(driver, max_clicks: int = 60, stale_limit: int = 3) -> None:
    click_count = 0
    stale_count = 0
    previous_count = len(extract_brand_records(driver))

    while click_count < max_clicks:
        show_more_btn = None
        for by, loc in [
            (By.CSS_SELECTOR, "button[data-cy='advertisers-results-button']"),
            (By.XPATH, "//button[.//div[contains(text(),'more results')]]"),
            (By.XPATH, "//button[contains(., 'more results')]"),
        ]:
            show_more_btn = _find_el_clickable(driver, by, loc, timeout=5)
            if show_more_btn:
                break

        if not show_more_btn:
            print(f"INFO: 未找到 'Show more results' 按钮，停止加载 (点击了 {click_count} 次)")
            return

        click_count += 1
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", show_more_btn)
            time.sleep(0.5)
            _click_el(driver, show_more_btn)
            print(f"INFO: 点击 'Show more results' 第 {click_count} 次...")
        except Exception as e:
            print(f"WARN: 点击 'Show more results' 失败: {e}")
            return

        time.sleep(3)
        current_count = len(extract_brand_records(driver))
        if current_count <= previous_count:
            stale_count += 1
            print(f"INFO: 品牌数量未增长 ({current_count})，连续 {stale_count}/{stale_limit}")
            if stale_count >= stale_limit:
                print("INFO: 连续点击后无新增品牌，停止加载")
                return
        else:
            print(f"INFO: 当前已加载品牌数 {current_count}")
            previous_count = current_count
            stale_count = 0

    print(f"WARN: 已达到最大点击次数 {max_clicks}，停止加载")


def extract_brand_records(driver) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    seen = set()

    cards = driver.find_elements(By.CSS_SELECTOR, "div[class*='CardWrapper']")
    for card in cards:
        try:
            name_el = card.find_element(By.CSS_SELECTOR, "div.Truncated, div[class*='Truncated']")
            brand = (name_el.text or "").strip()
            if not brand:
                continue

            brand_url = ""
            links = card.find_elements(By.CSS_SELECTOR, "a[href]")
            for link in links:
                href = (link.get_attribute("href") or "").strip()
                if href and "/advertisers/" in href:
                    brand_url = href
                    break

            key = (normalize_brand(brand), brand_url)
            if key in seen:
                continue
            seen.add(key)
            records.append({"brand": brand, "brand_url": brand_url})
        except Exception:
            continue

    if records:
        print(f"INFO: 提取到 {len(records)} 条品牌记录")
        return records

    print("WARN: CardWrapper 提取失败，使用备用方式...")
    fallback_elements = driver.find_elements(By.CSS_SELECTOR, "div.Truncated, div[class*='Truncated']")
    for el in fallback_elements:
        try:
            brand = (el.text or "").strip()
            if not brand or len(brand) >= 80:
                continue
            key = (normalize_brand(brand), "")
            if key in seen:
                continue
            seen.add(key)
            records.append({"brand": brand, "brand_url": ""})
        except Exception:
            continue

    print(f"INFO: 备用方式提取到 {len(records)} 条品牌记录")
    return records


def build_branlist_record(
    subject_id: str,
    env_serial: str,
    category: str,
    brand: str,
    brand_url: str,
    source_type: str,
    search_keyword: str,
) -> Dict[str, str]:
    return {
        "subject_id": subject_id,
        "env_serial": str(env_serial),
        "category": category,
        "brand": brand,
        "brand_url": brand_url,
        "apply_status": APPLY_STATUS_PENDING,
        "note": "",
        "source_type": source_type,
        "search_keyword": search_keyword,
        "discovered_at": now_iso(),
    }


def update_task_status(
    sheet_name: str,
    row_index: int,
    header_map: Dict[str, int],
    status: str,
    note: str,
    service=None,
    extra: Optional[Dict[str, str]] = None,
):
    values = {
        "status": status,
        "last_crawled_at": now_iso(),
        "note": note,
    }
    if extra:
        values.update(extra)
    update_sheet_row(get_spreadsheet_id(), sheet_name, row_index, header_map, values, service=service)
    print(f"INFO: 已更新 {sheet_name} 第 {row_index} 行状态='{status}'")


def process_category_task(
    driver,
    task: Dict[str, Any],
    existing_brands: set,
    service=None,
) -> Tuple[List[Dict[str, str]], str, str, int]:
    category = task["category"]
    url = task["url"]

    print(f"\n{'─' * 50}")
    print(f"  处理分类: {category}")
    print(f"  行号: {task['row_index']}")
    print(f"{'─' * 50}")

    driver.get(url)
    time.sleep(2)
    _wait_page_full_load(driver, timeout=30)

    if _is_login_page(driver):
        print("WARN: 分类页要求重新登录")
        if not login_rakuten(driver):
            return [], TASK_STATUS_FAILED, "re-login failed", 0
        driver.get(url)
        _wait_page_full_load(driver, timeout=30)

    total_count = get_total_brand_count(driver)
    if total_count:
        print(f"INFO: 分类 '{category}' 总数={total_count}")

    print("INFO: 开始加载分类所有品牌...")
    load_all_brands(driver)
    extracted = extract_brand_records(driver)

    new_records = []
    for item in extracted:
        normalized = normalize_brand(item["brand"])
        if not normalized or normalized in existing_brands:
            continue
        existing_brands.add(normalized)
        new_records.append(
            build_branlist_record(
                subject_id=task["subject_id"],
                env_serial=task["env_serial"],
                category=category,
                brand=item["brand"],
                brand_url=item["brand_url"],
                source_type=SOURCE_CATEGORY,
                search_keyword="",
            )
        )

    actual_count = len(extracted)
    if actual_count == 0:
        return [], TASK_STATUS_FAILED, "no brands extracted", 0
    if total_count and actual_count < total_count:
        return new_records, TASK_STATUS_PARTIAL, f"extracted {actual_count} of {total_count}", actual_count
    return new_records, TASK_STATUS_DONE, f"extracted {actual_count}", actual_count


def open_search_page(driver) -> bool:
    print(f"INFO: 导航到搜索页面: {ADVERTISERS_SEARCH_URL}")
    driver.get(ADVERTISERS_SEARCH_URL)
    _wait_page_full_load(driver, timeout=30)
    if _is_login_page(driver):
        print("WARN: 搜索页要求重新登录")
        if not login_rakuten(driver):
            return False
        driver.get(ADVERTISERS_SEARCH_URL)
        _wait_page_full_load(driver, timeout=30)
    return True


def fill_search_keyword(driver, keyword: str) -> bool:
    search_input = None
    for by, loc in [
        (By.CSS_SELECTOR, "input.AdvancedSearchBar__input"),
        (By.XPATH, "//input[contains(@placeholder, 'Search by Advertiser')]"),
    ]:
        search_input = _find_el_clickable(driver, by, loc, timeout=10)
        if search_input:
            break
    if not search_input:
        print("ERROR: 未找到搜索框")
        return False

    try:
        search_input.click()
        ActionChains(driver).key_down(Keys.COMMAND).send_keys("a").key_up(Keys.COMMAND).send_keys(Keys.BACKSPACE).perform()
    except Exception:
        try:
            search_input.clear()
        except Exception:
            pass

    time.sleep(0.5)
    search_input.send_keys(keyword)
    time.sleep(1)

    search_btn = None
    for by, loc in [
        (By.CSS_SELECTOR, "button.AdvancedSearchBar__button[aria-label='Search']"),
        (By.XPATH, "//button[@type='submit' and @aria-label='Search']"),
    ]:
        search_btn = _find_el_clickable(driver, by, loc, timeout=5)
        if search_btn:
            break

    if search_btn:
        _click_el(driver, search_btn)
    else:
        search_input.send_keys(Keys.ENTER)

    _wait_page_full_load(driver, timeout=30)
    time.sleep(2)
    return True


def process_keyword_task(
    driver,
    task: Dict[str, Any],
    existing_brands: set,
) -> Tuple[List[Dict[str, str]], str, str]:
    keyword = task["keyword"]

    print(f"\n{'─' * 50}")
    print(f"  处理关键词: {keyword}")
    print(f"  行号: {task['row_index']}")
    print(f"{'─' * 50}")

    if not open_search_page(driver):
        return [], TASK_STATUS_FAILED, "search page login failed"
    if not fill_search_keyword(driver, keyword):
        return [], TASK_STATUS_FAILED, "search input not found"

    result_state, total_count = wait_for_search_results_ready(driver, timeout=20)
    print(f"INFO: 关键词 '{keyword}' 总数={total_count}")

    if result_state == "empty":
        return [], TASK_STATUS_DONE, "no results"
    if result_state == "timeout":
        print("WARN: 搜索结果等待超时，继续尝试提取当前已加载内容")

    load_all_brands(driver)
    extracted = extract_brand_records(driver)
    if not extracted:
        if result_state == "timeout":
            return [], TASK_STATUS_FAILED, "search results not loaded"
        return [], TASK_STATUS_DONE, "no results"

    new_records = []
    for item in extracted:
        normalized = normalize_brand(item["brand"])
        if not normalized or normalized in existing_brands:
            continue
        existing_brands.add(normalized)
        new_records.append(
            build_branlist_record(
                subject_id=task["subject_id"],
                env_serial=task["env_serial"],
                category="",
                brand=item["brand"],
                brand_url=item["brand_url"],
                source_type=SOURCE_KEYWORD,
                search_keyword=keyword,
            )
        )

    actual_count = len(extracted)
    if actual_count < total_count:
        return new_records, TASK_STATUS_PARTIAL, f"extracted {actual_count} of {total_count}"
    return new_records, TASK_STATUS_DONE, f"extracted {actual_count}"



# =====================
# 主流程
# =====================
def process(subject_id: str, env_serial: str, email: str = None, password: str = None, close_on_finish: bool = False) -> bool:
    driver, env_id = open_env_by_serial(env_serial)
    if not driver:
        print(f"ERROR: 指纹环境启动失败 (序号: {env_serial})")
        return False

    try:
        print(f"\n{'=' * 55}")
        print("  Rakuten Advertising Publisher 采集")
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

        caturl_tasks, caturl_header_map = read_caturl_tasks(service, subject_id, env_serial)
        keyword_tasks, keyword_header_map = read_keyword_tasks(service, subject_id, env_serial)
        existing_brands, _ = read_existing_brands(service, subject_id)

        total_new_records = 0

        for task in caturl_tasks:
            if task["status"] in {TASK_STATUS_DONE, TASK_STATUS_DISABLED}:
                print(f"INFO: 分类 '{task['category']}' 已完成，跳过")
                continue
            records, status, note, extracted_count = process_category_task(driver, task, existing_brands, service=service)
            if records:
                append_branlist_records(records, service=service)
                total_new_records += len(records)

            extra = {}
            if "count" in caturl_header_map:
                extra["count"] = str(extracted_count) if status != TASK_STATUS_FAILED else task["count"]
            update_task_status(
                CATURL_SHEET,
                task["row_index"],
                caturl_header_map,
                status=status,
                note=note,
                service=service,
                extra=extra,
            )
            time.sleep(TASK_INTERVAL)

        for task in keyword_tasks:
            if task["status"] in {TASK_STATUS_DONE, TASK_STATUS_DISABLED}:
                print(f"INFO: 关键词 '{task['keyword']}' 已完成，跳过")
                continue
            records, status, note = process_keyword_task(driver, task, existing_brands)
            if records:
                append_branlist_records(records, service=service)
                total_new_records += len(records)

            update_task_status(
                KEYWORDS_SHEET,
                task["row_index"],
                keyword_header_map,
                status=status,
                note=note,
                service=service,
            )
            time.sleep(TASK_INTERVAL)

        print(f"\n{'=' * 55}")
        print("  采集完成!")
        print(f"  新增品牌数: {total_new_records}")
        print(f"{'=' * 55}")
        return True
    except KeyboardInterrupt:
        print(f"\nINFO: 用户中断执行 (Ctrl+C)")
        print(f"INFO: 已采集 {total_new_records} 条新记录")
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
    setup_logger("rakuten_aff_offer")

    parser = argparse.ArgumentParser(description="Rakuten Advertising Publisher 采集脚本")
    parser.add_argument("--subject-id", type=str, default=None, help="运行主体 ID，默认等于 --env-serial")
    parser.add_argument("--env-serial", "-s", type=str, required=True, help="AdsPower 指纹id")
    parser.add_argument("--email", "-e", type=str, default=None, help="登录邮箱，默认从 King 读取")
    parser.add_argument("--password", "-p", type=str, default=None, help="登录密码，默认从 King 读取")
    parser.add_argument("--close-on-finish", action="store_true", help="执行完成后关闭 AdsPower 浏览器")
    args = parser.parse_args()
    subject_id = args.subject_id or args.env_serial

    print("INFO: 正在预加载指纹缓存...")
    preload_fingerprint_cache()

    email = args.email
    password = args.password
    if not email or not password:
        email, password, resolved_env = resolve_subject_credentials(get_spreadsheet_id(), get_sheets_service(), normalize_subject_id(subject_id))
        if not args.subject_id and resolved_env != args.env_serial:
            print(f"WARN: King 中主体当前绑定指纹id为 {resolved_env}，本次仍按命令行 env_serial={args.env_serial} 执行")

    try:
        success = process(
            subject_id=subject_id,
            env_serial=args.env_serial,
            email=email,
            password=password,
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
