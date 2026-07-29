import os

import requests
from dotenv import load_dotenv

from prompts import GLOBAL_SYSTEM_PROMPT

load_dotenv()

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = os.getenv("ZAI_MODEL", "glm-4.5")


def call_glm(
    prompt: str,
    system_prompt: str = GLOBAL_SYSTEM_PROMPT,
    timeout: int = 120,
) -> str:

    api_key = os.getenv("ZAI_API_KEY")

    if not api_key:
        raise RuntimeError("缺少 ZAI_API_KEY")

    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        },
        timeout=timeout,
    )

    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"GLM 返回非 JSON：HTTP {response.status_code}"
        ) from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"GLM 请求失败：HTTP {response.status_code}，{result}"
        )

    choices = result.get("choices") or []

    if not choices:
        raise RuntimeError(f"GLM 返回缺少 choices：{result}")

    content = (
        choices[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )

    if not content:
        raise RuntimeError("GLM 返回内容为空")

    return content
