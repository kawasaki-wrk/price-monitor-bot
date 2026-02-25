import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "products.json"
STATE_PATH = BASE_DIR / "state.json"


@dataclass
class ProductRule:
    name: str
    url: str
    selector: str
    wait_selector: str | None = None
    attribute: str | None = None
    target_price: float | None = None


def load_rules(config_path: Path) -> list[ProductRule]:
    if not config_path.exists():
        raise FileNotFoundError(
            f"設定ファイルが見つかりません: {config_path}. products.example.json を products.json にコピーしてください。"
        )

    with config_path.open("r", encoding="utf-8") as file:
        raw_config = json.load(file)

    rules: list[ProductRule] = []
    for item in raw_config.get("products", []):
        rules.append(
            ProductRule(
                name=item["name"],
                url=item["url"],
                selector=item["selector"],
                wait_selector=item.get("wait_selector"),
                attribute=item.get("attribute"),
                target_price=item.get("target_price"),
            )
        )
    return rules


def load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    with state_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    with state_path.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    chrome_binary = os.getenv("CHROME_BINARY")
    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")

    if chrome_binary:
        options.binary_location = chrome_binary

    if chromedriver_path:
        service = Service(executable_path=chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)

    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
            },
        )
    except Exception:
        # CDP コマンドは一部の環境・ブラウザバージョンで未対応のため、失敗しても続行する
        pass

    return driver


@contextmanager
def managed_driver() -> Iterator[webdriver.Chrome]:
    driver = build_driver()
    try:
        yield driver
    finally:
        driver.quit()


def fetch_price(rule: ProductRule, driver: webdriver.Chrome) -> float:
    driver.get(rule.url)

    selector_for_wait = rule.wait_selector or rule.selector
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector_for_wait))
        )
    except TimeoutException as exc:
        raise ValueError(
            f"待機セレクタのタイムアウト: '{selector_for_wait}' ({rule.name})"
        ) from exc

    def has_non_empty_price(_: webdriver.Chrome) -> bool:
        try:
            element = driver.find_element(By.CSS_SELECTOR, rule.selector)
            raw_value = (
                element.get_attribute(rule.attribute)
                if rule.attribute
                else element.get_attribute("textContent")
            )
            return bool(raw_value and raw_value.strip())
        except (NoSuchElementException, StaleElementReferenceException):
            return False

    try:
        WebDriverWait(driver, 20).until(has_non_empty_price)
    except TimeoutException as exc:
        raise ValueError(
            f"価格テキスト待機のタイムアウト: '{rule.selector}' ({rule.name})"
        ) from exc

    soup = BeautifulSoup(driver.page_source, "html.parser")
    node = soup.select_one(rule.selector)
    if not node:
        raise ValueError(f"価格要素が見つかりません: {rule.selector} ({rule.name})")

    raw_text = node.get(rule.attribute, "") if rule.attribute else node.get_text(strip=True)
    price = extract_price(raw_text)
    if price is None:
        raise ValueError(f"価格の抽出に失敗しました: '{raw_text}' ({rule.name})")

    return price


def extract_price(text: str) -> float | None:
    normalized = text.replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if not match:
        return None
    return float(match.group(1))


def send_slack(webhook_url: str, message: str) -> None:
    response = requests.post(
        webhook_url,
        json={"text": message},
        timeout=15,
    )
    response.raise_for_status()


def send_discord(webhook_url: str, message: str) -> None:
    response = requests.post(
        webhook_url,
        json={"content": message},
        timeout=15,
    )
    response.raise_for_status()


def notify(message: str) -> None:
    slack_webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    discord_webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    if not slack_webhook and not discord_webhook:
        print("通知先が未設定です。SLACK_WEBHOOK_URL または DISCORD_WEBHOOK_URL を設定してください。")
        return

    if slack_webhook:
        try:
            send_slack(slack_webhook, message)
        except Exception as exc:
            print(f"[ERROR] Slack通知失敗: {exc}")

    if discord_webhook:
        try:
            send_discord(discord_webhook, message)
        except Exception as exc:
            print(f"[ERROR] Discord通知失敗: {exc}")


def create_message(rule: ProductRule, old_price: float | None, current_price: float) -> str:
    if old_price is None:
        if rule.target_price is None:
            raise ValueError(f"target_price が未設定の状態で通知メッセージを生成できません: {rule.name}")
        return (
            f"🎯 初回計測で目標価格到達: {rule.name}\n"
            f"現在価格: {current_price:.0f}円 (目標: {rule.target_price:.0f}円 以下)\n"
            f"{rule.url}"
        )

    diff = current_price - old_price
    if diff < 0:
        return (
            f"📉 値下がり検知: {rule.name}\n"
            f"前回: {old_price:.0f}円 → 今回: {current_price:.0f}円 ({diff:.0f}円)\n"
            f"{rule.url}"
        )

    if rule.target_price is None:
        raise ValueError(f"target_price が未設定の状態で通知メッセージを生成できません: {rule.name}")
    return (
        f"🎯 目標価格到達: {rule.name}\n"
        f"現在価格: {current_price:.0f}円 (目標: {rule.target_price:.0f}円 以下)\n"
        f"{rule.url}"
    )


def should_notify(rule: ProductRule, old_price: float | None, current_price: float) -> bool:
    if old_price is None:
        return rule.target_price is not None and current_price <= rule.target_price

    price_dropped = current_price < old_price
    target_reached = (
        rule.target_price is not None
        and current_price <= rule.target_price
        and old_price > rule.target_price
    )
    return price_dropped or target_reached


def main() -> None:
    load_dotenv(BASE_DIR / ".env")

    rules = load_rules(CONFIG_PATH)
    state = load_state(STATE_PATH)

    if not rules:
        print("products.json に監視対象がありません。")
        return

    with managed_driver() as driver:
        for rule in rules:
            try:
                current_price = fetch_price(rule, driver)
            except Exception as exc:
                print(f"[ERROR] {rule.name}: {exc}")
                continue

            old_price = state.get(rule.name, {}).get("last_price")

            if should_notify(rule, old_price, current_price):
                message = create_message(rule, old_price, current_price)
                notify(message)

            state[rule.name] = {
                "last_price": current_price,
                "url": rule.url,
                "updated_at": int(time.time()),
            }
            print(f"[OK] {rule.name}: {current_price:.0f}円")

    save_state(STATE_PATH, state)


if __name__ == "__main__":
    main()
