from zai import ZhipuAiClient
import os

API_KEY = os.getenv("ZHIPU_API_KEY")

if not API_KEY:
    raise Exception("请先设置 ZHIPU_API_KEY")

client = ZhipuAiClient(
    api_key=API_KEY
)

print("=== 测试 GLM Web Search ===")

response = client.chat.completions.create(
    model="glm-4.5",
    messages=[
        {
            "role": "user",
            "content": "搜索并总结 Uni3C: Unifying Precisely 3D-Enhanced Camera and Human Motion Controls for Video Generation 这篇论文"
        }
    ],
    tools=[
        {
            "type": "web_search",
            "web_search": {
                "enable": True
            }
        }
    ]
)

print("\n===== 返回结果 =====\n")

print(response.choices[0].message.content)

print("\n===== 完整响应 =====\n")
print(response)
