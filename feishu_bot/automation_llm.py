"""LLM provider used by scheduled research and publishing workflows."""
from __future__ import annotations

import os

from dotenv import load_dotenv

from glm_client import call_glm as call_zai_glm
from prompts import GLOBAL_SYSTEM_PROMPT


load_dotenv()


def call_automation_llm(
    prompt: str,
    system_prompt: str = GLOBAL_SYSTEM_PROMPT,
    timeout: int = 120,
    web_search: bool = False,
    search_prompt: str = "",
    search_count: int = 8,
) -> str:
    """Run an automation prompt through Yuanbao by default.

    The signature intentionally matches ``glm_client.call_glm`` so existing
    paper/news modules can switch providers without changing their prompts.
    """
    provider = os.getenv("AUTOMATION_LLM_PROVIDER", "yuanbao").strip().casefold()
    if provider in {"yuanbao", "deepseek", "yuanbao_deepseek"}:
        from yuanbao_agent import ask_yuanbao

        instructions = [system_prompt.strip(), prompt.strip()]
        if web_search:
            instructions.append(
                "本任务允许并要求使用元宝联网检索。只采用官方网页、论文主页、"
                "官方代码仓库或输入中明确允许的一手来源；无法核验就留空，不得猜测。"
            )
            if search_prompt:
                instructions.append("检索要求：" + search_prompt)
        return ask_yuanbao(
            "\n\n".join(value for value in instructions if value),
            raw=True,
            timeout=max(30, int(timeout)),
        )
    if provider in {"chatgpt", "chatgpt_web", "gpt_web"}:
        from chatgpt_agent import ask_chatgpt

        instructions = [system_prompt.strip(), prompt.strip()]
        if web_search:
            instructions.append(
                "本任务必须联网检索。只采用官方网页、论文主页、官方代码仓库"
                "或输入中明确允许的一手来源；无法核验就留空，不得猜测。"
            )
            if search_prompt:
                instructions.append("检索要求：" + search_prompt)
        return ask_chatgpt(
            "\n\n".join(value for value in instructions if value),
            timeout=max(30, int(timeout)),
        )
    if provider in {"codex", "codex_cli", "server_codex"}:
        from codex_automation import ask_codex

        instructions = [system_prompt.strip(), prompt.strip()]
        if web_search:
            instructions.append(
                "本任务需要核验最新公开信息。优先检查官方网页、论文主页、"
                "官方代码仓库或输入中提供的一手来源；无法核验就留空，不得猜测。"
            )
            if search_prompt:
                instructions.append("核验要求：" + search_prompt)
        return ask_codex(
            "\n\n".join(value for value in instructions if value),
            timeout=max(30, int(timeout)),
        )
    if provider in {"glm", "zai", "zhipu"}:
        return call_zai_glm(
            prompt,
            system_prompt=system_prompt,
            timeout=timeout,
            web_search=web_search,
            search_prompt=search_prompt,
            search_count=search_count,
        )
    raise RuntimeError(f"不支持的 AUTOMATION_LLM_PROVIDER：{provider}")
