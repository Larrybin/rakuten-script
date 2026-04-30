"""
selenium_helpers.py
===================
共享 Selenium 工具函数，供 rakuten_aff_apply / rakuten_aff_offer 等脚本复用。
"""

import time

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def find_el(driver, by, loc, timeout: int = 8):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, loc))
        )
    except Exception:
        return None


def find_el_clickable(driver, by, loc, timeout: int = 8):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, loc))
        )
    except Exception:
        return None


def click_el(driver, el) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass
    try:
        ActionChains(driver).move_to_element(el).pause(0.1).click(el).perform()
        return True
    except Exception:
        pass
    try:
        el.click()
        return True
    except Exception:
        pass
    try:
        driver.execute_script("arguments[0].click();", el)
        return True
    except Exception:
        return False


def wait_page_stable(driver, timeout: int = 10) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            state = driver.execute_script("return document.readyState")
            if state == "complete":
                return
        except Exception:
            return
        time.sleep(0.5)


def wait_page_full_load(driver, timeout: int = 30) -> bool:
    print(f"INFO: 等待页面完全加载 (最大 {timeout} 秒)...")
    start = time.time()
    wait_page_stable(driver, timeout=timeout)

    last_len = 0
    stable_count = 0
    while time.time() - start < timeout:
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text or ""
            current_len = len(body_text)
            if current_len > 0 and current_len == last_len:
                stable_count += 1
                if stable_count >= 2:
                    print(f"INFO: 页面内容已稳定 (耗时 {time.time() - start:.1f} 秒)")
                    return True
            else:
                stable_count = 0
            last_len = current_len
        except Exception:
            pass
        time.sleep(0.5)

    print(f"WARN: 页面加载等待达到上限 ({time.time() - start:.1f} 秒)")
    return True


def wait_until(driver, condition_fn, timeout: int = 10, min_wait: float = 0,
               poll_interval: float = 0.5, description: str = "condition"):
    """
    智能等待：轮询 condition_fn 直到返回 truthy 值。
    - min_wait: 最短等待秒数（即使条件已满足也要等够，保证网络稳定性）
    - timeout: 最长等待秒数
    - 返回 condition_fn 的结果，超时则返回 None
    """
    start = time.time()
    result = None
    while True:
        elapsed = time.time() - start
        if elapsed >= timeout:
            break
        try:
            result = condition_fn()
            if result and elapsed >= min_wait:
                return result
        except Exception:
            pass
        time.sleep(poll_interval)
    # 最后再试一次
    try:
        result = condition_fn()
    except Exception:
        pass
    return result


def safe_navigate(driver, url: str, timeout: int = 30, retries: int = 2) -> bool:
    """
    带重试机制的页面导航。
    """
    for attempt in range(retries + 1):
        try:
            driver.set_page_load_timeout(timeout)
            driver.get(url)
            wait_page_full_load(driver, timeout=timeout)
            return True
        except Exception as e:
            if attempt >= retries:
                print(f"ERROR: 导航失败 ({url[:60]}): {e}")
                return False
            print(f"WARN: 导航超时，重试 ({attempt + 1}/{retries})")
    return False
