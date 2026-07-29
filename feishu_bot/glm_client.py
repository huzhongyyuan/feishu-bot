import os
import requests
from dotenv import load_dotenv

load_dotenv()


ZAI_API_KEY = os.getenv("ZAI_API_KEY")


def call_glm(question):

    r = requests.post(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ZAI_API_KEY}"
        },
        json={
            "model": "glm-4.5",
            "messages": [
                {
                    "role": "user",
                    "content": question
                }
            ]
        },
        timeout=120
    )

    data = r.json()

    return (
        data["choices"][0]
        ["message"]
        ["content"]
    )
