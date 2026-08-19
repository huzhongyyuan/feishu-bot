"""Refresh the Yuanbao browser login state locally or on a headless server."""
from __future__ import annotations

import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


APP_DIR = Path(__file__).resolve().parent
STATE_PATH = Path(
    os.getenv("YUANBAO_STATE_FILE", APP_DIR / "state" / "yuanbao_state.json")
)
SCREENSHOT_PATH = Path(
    os.getenv("YUANBAO_LOGIN_SCREENSHOT", APP_DIR / "state" / "yuanbao_login.png")
)


def _enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _logged_in(page) -> bool:
    """Use authenticated-only model controls instead of the composer itself."""
    return page.locator("[aria-label='深度思考']").count() > 0 and page.locator(
        "[aria-label='深度思考']"
    ).first.is_visible()


def main() -> None:
    headless = _enabled("YUANBAO_LOGIN_HEADLESS")
    timeout_seconds = int(os.getenv("YUANBAO_LOGIN_TIMEOUT_SECONDS", "600"))
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(
            "https://yuanbao.tencent.com/",
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        if not headless:
            input("完成元宝登录后按回车：")
        else:
            deadline = time.monotonic() + timeout_seconds
            print(f"请扫描二维码：{SCREENSHOT_PATH}", flush=True)
            while time.monotonic() < deadline:
                page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
                if _logged_in(page):
                    break
                page.wait_for_timeout(2_000)
            else:
                raise RuntimeError("等待元宝扫码登录超时。")

        context.storage_state(path=str(STATE_PATH))
        page.screenshot(path=str(SCREENSHOT_PATH), full_page=True)
        print(f"元宝登录态已保存：{STATE_PATH}", flush=True)
        browser.close()


if __name__ == "__main__":
    main()
