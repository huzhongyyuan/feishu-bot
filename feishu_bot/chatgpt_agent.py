import os
import threading
import time
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


_REQUEST_LOCK = threading.Lock()
_ASSISTANT_SELECTOR = '[data-message-author-role="assistant"]'
_COMPOSER_SELECTOR = "#prompt-textarea, textarea, [contenteditable=true]"


class ChatGPTWebError(RuntimeError):
    """A safe, user-facing ChatGPT web failure."""


def _find_chatgpt_page(browser):
    for context in browser.contexts:
        for page in context.pages:
            if page.url.startswith("https://chatgpt.com"):
                return page

    if not browser.contexts:
        raise ChatGPTWebError("服务器浏览器上下文不存在，请检查后台浏览器。")
    return browser.contexts[0].new_page()


def _visible_composer(page):
    composers = page.locator(_COMPOSER_SELECTOR)
    for index in range(composers.count()):
        candidate = composers.nth(index)
        if candidate.is_visible():
            return candidate
    raise ChatGPTWebError("未找到 ChatGPT 输入框，请检查登录状态。")


def _unique_links(turn) -> list[str]:
    links = []
    for href in turn.locator("a[href]").evaluate_all(
        "elements => elements.map(element => element.href)"
    ):
        parsed = urlparse(str(href))
        if parsed.scheme in {"http", "https"} and href not in links:
            links.append(href)
    return links


def _wait_for_answer(page, previous_count: int, timeout_seconds: int) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_text = ""
    stable_samples = 0

    while time.monotonic() < deadline:
        turns = page.locator(_ASSISTANT_SELECTOR)
        if turns.count() > previous_count:
            turn = turns.last
            text = turn.inner_text().strip()
            generating = page.locator(
                'button[data-testid="stop-button"], button[aria-label*="Stop"]'
            ).count()

            if text and text == last_text and not generating:
                stable_samples += 1
            else:
                stable_samples = 0
            last_text = text

            if stable_samples >= 3:
                links = _unique_links(turn)
                missing_links = [url for url in links if url not in text]
                if missing_links:
                    text += "\n\n参考链接\n" + "\n".join(missing_links)
                return text

        page.wait_for_timeout(1000)

    raise ChatGPTWebError("等待 ChatGPT 回答超时，请稍后重试。")


def ask_chatgpt(question: str) -> str:
    question = question.strip()
    if not question:
        raise ChatGPTWebError("请在 GPT 后面填写问题。")
    if not _REQUEST_LOCK.acquire(blocking=False):
        raise ChatGPTWebError("ChatGPT 正在回答上一条问题，请稍后再试。")

    endpoint = os.getenv(
        "CHATGPT_CDP_URL",
        "http://127.0.0.1:9222",
    ).strip()
    timeout_seconds = max(
        30,
        int(os.getenv("CHATGPT_ANSWER_TIMEOUT_SECONDS", "180")),
    )

    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(
                    endpoint,
                    timeout=15_000,
                )
            except PlaywrightTimeoutError as exc:
                raise ChatGPTWebError(
                    "无法连接服务器 ChatGPT 浏览器，请检查后台服务。"
                ) from exc

            page = _find_chatgpt_page(browser)
            page.goto(
                "https://chatgpt.com/",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            page.wait_for_timeout(1500)

            if page.get_by_role("button", name="Log in", exact=True).count():
                raise ChatGPTWebError("ChatGPT 登录已失效，需要重新登录。")

            previous_count = page.locator(_ASSISTANT_SELECTOR).count()
            composer = _visible_composer(page)
            composer.fill(question)
            composer.press("Enter")
            return _wait_for_answer(page, previous_count, timeout_seconds)
    except ChatGPTWebError:
        raise
    except PlaywrightTimeoutError as exc:
        raise ChatGPTWebError("ChatGPT 页面响应超时，请稍后重试。") from exc
    except Exception as exc:
        raise ChatGPTWebError("ChatGPT 网页调用失败，请检查服务器日志。") from exc
    finally:
        _REQUEST_LOCK.release()
