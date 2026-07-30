import os
import re
import threading
import time
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


_REQUEST_LOCK = threading.Lock()
_ASSISTANT_SELECTOR = '[data-message-author-role="assistant"]'
_COMPOSER_SELECTOR = "#prompt-textarea, textarea, [contenteditable=true]"
_CITATION_NOISE = re.compile(
    r"^(?:\+\d+|X \(formerly Twitter\)|AI IDE List)$",
    re.IGNORECASE,
)
_SECTION_HEADING = re.compile(
    r"^(?:#{1,6}\s*)?(?:"
    r"\d+[.、]\s*|"
    r"[一二三四五六七八九十]+[、.]\s*|"
    r"[\U0001F300-\U0001FAFF]"
    r")"
)


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


def _clean_url(url: str) -> str:
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunparse(parsed._replace(query=urlencode(query)))


def _unique_links(turn) -> list[str]:
    links = []
    for href in turn.locator("a[href]").evaluate_all(
        "elements => elements.map(element => element.href)"
    ):
        parsed = urlparse(str(href))
        cleaned = _clean_url(str(href))
        if parsed.scheme in {"http", "https"} and cleaned not in links:
            links.append(cleaned)
    return links


def _format_table(lines: list[str], start: int) -> tuple[list[str], int]:
    rows = []
    index = start
    while index < len(lines) and "\t" in lines[index]:
        columns = [item.strip() for item in lines[index].split("\t")]
        if len(columns) < 2:
            break
        rows.append(columns)
        index += 1

    if len(rows) < 2:
        return [lines[start]], start + 1

    headers = rows[0]
    formatted = []
    for number, row in enumerate(rows[1:], start=1):
        formatted.append(f"{number}. {row[0]}")
        for column_index, value in enumerate(row[1:], start=1):
            if not value:
                continue
            label = (
                headers[column_index]
                if column_index < len(headers)
                else f"信息{column_index}"
            )
            formatted.append(f"   {label}：{value}")
    return formatted, index


def format_chatgpt_answer(
    text: str,
    links: Optional[list[str]] = None,
) -> str:
    raw_lines = [
        line.replace("\u00a0", " ").strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    lines = [
        re.sub(r"^•\s*", "- ", line)
        for line in raw_lines
        if line and not _CITATION_NOISE.fullmatch(line)
    ]

    compact = []
    index = 0
    while index < len(lines):
        if "\t" in lines[index]:
            table_lines, index = _format_table(lines, index)
            compact.extend(table_lines)
            continue
        compact.append(lines[index])
        index += 1

    visible_links = []
    body_lines = []
    for line in compact:
        if re.fullmatch(r"https?://\S+", line):
            cleaned = _clean_url(line)
            if cleaned not in visible_links:
                visible_links.append(cleaned)
            continue
        body_lines.append(line)

    for link in links or []:
        cleaned = _clean_url(link)
        if cleaned not in visible_links:
            visible_links.append(cleaned)

    output = []
    for line in body_lines:
        is_heading = (
            bool(_SECTION_HEADING.match(line))
            or line.rstrip("：:") in {"参考链接", "参考资料", "来源"}
            or line.endswith(("趋势", "影响", "方向"))
        )
        if is_heading and output and output[-1] != "":
            output.append("")
        output.append(line)

    if visible_links:
        if output and output[-1] != "":
            output.append("")
        if not output or output[-1] != "参考链接":
            output.append("参考链接")
        output.extend(visible_links)

    formatted = "\n".join(output).strip()
    formatted = re.sub(r"\n{3,}", "\n\n", formatted)
    max_chars = max(
        1000,
        int(os.getenv("CHATGPT_MAX_ANSWER_CHARS", "12000")),
    )
    if len(formatted) > max_chars:
        formatted = formatted[: max_chars - 12].rstrip() + "\n\n[内容已截断]"
    return formatted


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
                return format_chatgpt_answer(text, links)

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
