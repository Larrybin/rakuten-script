import rakuten_aff_apply
import rakuten_aff_offer
from lib.selenium_input import fill_input_value


class DummyInput:
    def __init__(self, initial_value=""):
        self.value = initial_value
        self.sent = []

    def clear(self):
        self.value = ""

    def send_keys(self, text):
        self.sent.append(text)
        self.value += text

    def get_attribute(self, name):
        if name == "value":
            return self.value
        return ""


class DummyDriver:
    def __init__(self):
        self.scripts = []

    def execute_script(self, script, element, value):
        self.scripts.append((script, value))
        element.value = value


def test_shared_fill_input_overwrites_existing_value():
    driver = DummyDriver()
    element = DummyInput("old@example.com")

    fill_input_value(driver, element, "new@example.com")

    assert element.get_attribute("value") == "new@example.com"


def test_shared_fill_input_uses_js_fallback_when_send_keys_appends():
    driver = DummyDriver()
    element = DummyInput("prefilled")

    def broken_clear():
        return None

    def append_only_send_keys(text):
        element.value += text

    element.clear = broken_clear
    element.send_keys = append_only_send_keys

    fill_input_value(driver, element, "abc@test.com")

    assert element.get_attribute("value") == "abc@test.com"
    assert driver.scripts


def test_apply_and_offer_use_shared_fill_input():
    assert rakuten_aff_apply.fill_input_value is fill_input_value
    assert rakuten_aff_offer.fill_input_value is fill_input_value
