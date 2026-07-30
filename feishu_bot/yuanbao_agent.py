"""Yuanbao web agent backed by an account-owner supplied login state."""
from __future__ import annotations

import os
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


logger = logging.getLogger(__name__)
_SECTION_RE = re.compile(r"^[一二三四五六七八九十]+、")
_BULLET_ONLY = {"•", "·", "-", "–", "—"}


def _format_answer(text: str) -> str:
    """Make Yuanbao's visual layout readable in a plain Feishu message."""
    result: list[str] = []
    pending_bullet = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in _BULLET_ONLY:
            pending_bullet = True
            continue

        if pending_bullet:
            line = f"• {line}"
            pending_bullet = False
        elif line.startswith(("•", "·")):
            line = f"• {line[1:].strip()}"

        if _SECTION_RE.match(line):
            if result and result[-1] != "":
                result.append("")
            result.extend((line, ""))
        else:
            result.append(line)

    while result and result[-1] == "":
        result.pop()
    return "\n".join(result)


def _latest_answer(page_text: str, question: str) -> str:
    marker = page_text.rfind(question)
    tail = page_text[marker + len(question) :] if marker >= 0 else page_text

    for control in (
        "\nDeep Thinking",
        "\nDownload for Desktop",
        "\nAI-generated content",
    ):
        tail = tail.split(control, 1)[0]

    return _format_answer(tail)


def _page_links(page) -> list[dict[str, str]]:
    return page.eval_on_selector_all(
        "a[href]",
        """anchors => anchors.map(anchor => ({
            text: (anchor.innerText || anchor.textContent || '').trim(),
            href: anchor.href || ''
        }))""",
    )


def _new_reference_links(
    before_hrefs: set[str],
    links: list[dict[str, str]],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()

    for link in links:
        href = str(link.get("href") or "").strip()
        text = " ".join(str(link.get("text") or "").split())
        parsed = urlparse(href)
        if (
            parsed.scheme not in {"http", "https"}
            or href in before_hrefs
            or href in seen
        ):
            continue
        seen.add(href)
        result.append({"text": text, "href": href})

    return result[:12]


def _append_reference_links(
    answer: str,
    links: list[dict[str, str]],
) -> str:
    if not links:
        return answer

    rows = []
    for index, link in enumerate(links, start=1):
        label = link["text"] or urlparse(link["href"]).netloc or f"来源 {index}"
        rows.append(f"{index}. {label}\n   {link['href']}")
    return answer.rstrip() + "\n\n参考链接\n\n" + "\n\n".join(rows)


def _wait_for_answer(page, question: str) -> str:
    deadline = time.monotonic() + float(
        os.getenv("YUANBAO_ANSWER_TIMEOUT_SECONDS", "90")
    )
    previous = ""
    stable_checks = 0

    while time.monotonic() < deadline:
        page.wait_for_timeout(2_500)
        text = page.locator("body").inner_text(timeout=20_000)
        answer = _latest_answer(text, question)
        if len(answer) < 20:
            continue
        if answer == previous:
            stable_checks += 1
            if stable_checks >= 3:
                return answer
        else:
            previous = answer
            stable_checks = 0

    if previous:
        return previous
    raise RuntimeError("元宝在限定时间内没有返回可读取的回答。")


def _env_enabled(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _configure_model(page) -> tuple[str, bool]:
    """Select and verify the requested Yuanbao model before every prompt."""
    requested_model = os.getenv("YUANBAO_MODEL", "deepseek").strip().lower()
    deep_thinking = _env_enabled("YUANBAO_DEEP_THINKING", default=True)
    think_button = page.locator("[aria-label='深度思考']")
    think_button.wait_for(state="visible", timeout=20_000)

    if requested_model in {"deepseek", "deep_seek"}:
        current_model_id = think_button.get_attribute("dt-model-id") or ""
        if not current_model_id.startswith("deep_seek"):
            model_button = page.locator("[aria-label='模型选择']")
            model_button.wait_for(state="visible", timeout=20_000)
            model_button.click()
            deepseek_option = page.locator(
                ".ybc-model-select-dropdown-item-name",
                has_text="DeepSeek",
            )
            if deepseek_option.count() != 1:
                raise RuntimeError("元宝模型菜单中未找到唯一的 DeepSeek 选项。")
            deepseek_option.click()
            page.wait_for_function(
                """() => {
                    const el = document.querySelector('[aria-label="深度思考"]');
                    return (el?.getAttribute('dt-model-id') || '')
                        .startsWith('deep_seek');
                }""",
                timeout=15_000,
            )
    elif requested_model not in {"yuanbao", "hunyuan", "hy3"}:
        raise RuntimeError(f"不支持的 YUANBAO_MODEL：{requested_model}")

    selected_class = think_button.get_attribute("class") or ""
    is_deep_thinking = "ThinkSelector_selected" in selected_class
    if deep_thinking != is_deep_thinking:
        think_button.click()
        page.wait_for_function(
            """enabled => {
                const el = document.querySelector('[aria-label="深度思考"]');
                const selected = (el?.className || '')
                    .includes('ThinkSelector_selected');
                return selected === enabled;
            }""",
            deep_thinking,
            timeout=15_000,
        )

    model_id = think_button.get_attribute("dt-model-id") or "unknown"
    selected_class = think_button.get_attribute("class") or ""
    is_deep_thinking = "ThinkSelector_selected" in selected_class
    if requested_model in {"deepseek", "deep_seek"} and not model_id.startswith(
        "deep_seek"
    ):
        raise RuntimeError(f"DeepSeek 模型校验失败，当前模型标识：{model_id}")
    if deep_thinking and not is_deep_thinking:
        raise RuntimeError("深度思考模式校验失败。")

    logger.info(
        "元宝模型配置完成 model_id=%s deep_thinking=%s",
        model_id,
        is_deep_thinking,
    )
    return model_id, is_deep_thinking


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
            _configure_model(page)
            before_hrefs = {
                link["href"]
                for link in _page_links(page)
                if link.get("href")
            }
            box.fill(question)
            box.press("Enter")
            answer = _wait_for_answer(page, question)
            links = _new_reference_links(before_hrefs, _page_links(page))
            answer = _append_reference_links(answer, links)
            max_chars = int(os.getenv("YUANBAO_MAX_ANSWER_CHARS", "12000"))
            return answer[:max_chars]
        except PlaywrightTimeoutError as exc:
            debug_path = state_file.parent / "yuanbao_debug.png"
            page.screenshot(path=str(debug_path), full_page=True)
            raise RuntimeError("元宝网页未加载完成或登录已失效。") from exc
        finally:
            context.close()
            browser.close()
