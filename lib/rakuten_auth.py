"""
rakuten_auth.py
===============
Rakuten Advertising Publisher 登录逻辑。
从 rakuten_aff_apply.py 提取的更健壮版本（优先 Enter 提交 + 按钮兜底）。
"""

import sys
import time

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from lib.selenium_helpers import find_el, find_el_clickable, click_el, wait_page_full_load
from lib.selenium_input import fill_input_value


def is_login_page(driver) -> bool:
    try:
        url = driver.current_url or ""
        if "auth" in url.lower() or "login" in url.lower() or "kc/" in url.lower():
            return True
        return bool(
            find_el(driver, By.ID, "username", timeout=2)
            or find_el(driver, By.ID, "kc-login", timeout=2)
        )
    except Exception:
        return False


def is_logged_in(driver) -> bool:
    try:
        url = driver.current_url or ""
        return (
            "publisher.rakutenadvertising.com" in url
            and "auth" not in url.lower()
            and "login" not in url.lower()
            and "kc/" not in url.lower()
        )
    except Exception:
        return False


def _press_enter_on_password(driver, password_input) -> bool:
    """Rakuten 登录页密码框回车提交比按钮点击更稳定。"""
    try:
        driver.execute_script("arguments[0].focus();", password_input)
    except Exception:
        pass

    try:
        password_input.send_keys(Keys.ENTER)
        return True
    except Exception:
        pass

    try:
        ActionChains(driver).move_to_element(password_input).click(password_input).send_keys(Keys.ENTER).perform()
        return True
    except Exception:
        pass

    try:
        driver.execute_script(
            """
            const el = arguments[0];
            el.focus();
            const eventInit = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true };
            el.dispatchEvent(new KeyboardEvent('keydown', eventInit));
            el.dispatchEvent(new KeyboardEvent('keypress', eventInit));
            el.dispatchEvent(new KeyboardEvent('keyup', eventInit));
            if (el.form) el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit();
            """,
            password_input,
        )
        return True
    except Exception:
        return False


def login_rakuten(driver, email: str = None, password: str = None) -> bool:
    """
    Rakuten Advertising Publisher 登录。
    优先使用密码框 Enter 提交（更稳定），兜底使用 Login 按钮。
    """
    if not email or not password:
        print("ERROR: 缺少 Rakuten 登录凭据")
        return False

    if is_logged_in(driver):
        print("✅ 已处于登录状态，无需重复登录")
        return True

    if not is_login_page(driver):
        print("INFO: 当前页面既非登录页也非已登录状态，等待页面继续加载...")
        time.sleep(5)
        if is_logged_in(driver):
            print("✅ 等待后确认已登录")
            return True
        if not is_login_page(driver):
            print("WARN: 无法识别当前页面状态")
            return False

    username_input = None
    for by, loc in [
        (By.ID, "username"),
        (By.CSS_SELECTOR, "input.login-input[name='username']"),
        (By.CSS_SELECTOR, "input[placeholder='Email address']"),
        (By.CSS_SELECTOR, "input[type='text'][name='username']"),
    ]:
        username_input = find_el_clickable(driver, by, loc, timeout=10)
        if username_input:
            break
    if not username_input:
        print("ERROR: 未找到邮箱输入框")
        return False

    fill_input_value(driver, username_input, email)

    password_input = None
    for by, loc in [
        (By.ID, "password"),
        (By.CSS_SELECTOR, "input.password-input[name='password']"),
        (By.CSS_SELECTOR, "input[type='password'][name='password']"),
        (By.CSS_SELECTOR, "input[type='password']"),
    ]:
        password_input = find_el_clickable(driver, by, loc, timeout=8)
        if password_input:
            break
    if not password_input:
        print("ERROR: 未找到密码输入框")
        return False

    fill_input_value(driver, password_input, password)

    print("INFO: 密码已输入，按 Enter 提交登录...")
    if _press_enter_on_password(driver, password_input):
        time.sleep(3)
        wait_page_full_load(driver, timeout=20)
        if is_logged_in(driver):
            print("✅ Rakuten Advertising 登录成功！")
            return True
    else:
        print("WARN: 密码框 Enter 提交失败，准备尝试 Login 按钮")

    login_btn = None
    for by, loc in [
        (By.ID, "kc-login"),
        (By.CSS_SELECTOR, "button.submit-button.login-button"),
        (By.CSS_SELECTOR, "button[name='login'][type='submit']"),
        (By.XPATH, "//button[contains(text(),'Login')]"),
    ]:
        login_btn = find_el_clickable(driver, by, loc, timeout=8)
        if login_btn:
            break

    print("INFO: Enter 后仍未确认登录，尝试点击 Login 按钮兜底...")
    if login_btn:
        click_el(driver, login_btn)
    else:
        password_input.send_keys(Keys.ENTER)

    time.sleep(3)
    wait_page_full_load(driver, timeout=30)
    for _ in range(3):
        if is_logged_in(driver):
            print("✅ Rakuten Advertising 登录成功！")
            return True
        time.sleep(5)
    return is_logged_in(driver)
