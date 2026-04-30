import sys

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

_MODIFIER = Keys.COMMAND if sys.platform == "darwin" else Keys.CONTROL


def fill_input_value(driver, element, value: str):
    safe_value = value or ""
    try:
        element.click()
    except Exception:
        pass
    try:
        element.clear()
    except Exception:
        pass
    try:
        ActionChains(driver).click(element).key_down(_MODIFIER).send_keys("a").key_up(_MODIFIER).send_keys(Keys.BACKSPACE).perform()
    except Exception:
        pass
    try:
        element.send_keys(safe_value)
    except Exception:
        pass

    current_value = ""
    try:
        current_value = element.get_attribute("value") or ""
    except Exception:
        current_value = ""

    if current_value != safe_value:
        driver.execute_script(
            "arguments[0].focus();"
            "arguments[0].value='';"
            "arguments[0].value=arguments[1];"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
            element,
            safe_value,
        )
