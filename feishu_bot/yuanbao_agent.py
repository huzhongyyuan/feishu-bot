"""Yuanbao web agent backed by an account-owner supplied login state."""
from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def _latest_answer(page_text: str, question: str) -> str:
    marker = page_text.rfind(question)
    tail = page_text[marker + len(question) :] if marker >= 0 else page_text

    for control in (
        "\nDeep Thinking",
        "\nDownload for Desktop",
        "\nAI-generated content",
    ):
        tail = tail.split(control, 1)[0]

    lines = [line.strip() for line in tail.splitlines() if line.strip()]
    return "\n".join(lines).strip()[:6000]


def ask_yuanbao(question: str) -> str:
    state_file = Path(
        os.getenv(
            "YUANBAO_STATE_FILE",
            Path(__file__).resolve().parent / "state" / "yuanbao_state.json",
        )
    )
    if not state_file.exists():
        raise RuntimeError("缺少元宝登录态文件，请先完成元宝登录。")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(state_file))
        page = context.new_page()

        try:
            page.goto(
                "https://yuanbao.tencent.com/",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            box = page.locator("textarea, [contenteditable='true']").first
            box.wait_for(state="visible", timeout=30_000)
            box.fill(question)
            box.press("Enter")
            page.wait_for_timeout(12_000)
            text = page.locator("body").inner_text(timeout=20_000)
            answer = _latest_answer(text, question)
            if not answer:
                raise RuntimeError("未能从元宝页面提取最新回答。")
            return answer
        except PlaywrightTimeoutError as exc:
            debug_path = state_file.parent / "yuanbao_debug.png"
            page.screenshot(path=str(debug_path), full_page=True)
            raise RuntimeError("元宝网页未加载完成或登录已失效。") from exc
        finally:
            context.close()
            browser.close()
