from fastapi import FastAPI, Request
import requests
import json
import os
from dotenv import load_dotenv
from event_db import init_event_db, exists, save
import lark_oapi as lark


load_dotenv()

app = FastAPI()

init_event_db()

# 飞书事件去重
PROCESSED_EVENT_IDS = set()


ZAI_API_KEY = os.getenv("ZAI_API_KEY")


def call_glm(question):

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ZAI_API_KEY}"
    }

    data = {
        "model": "glm-5.2",
        "messages": [
            {
                "role": "user",
                "content": question
            }
        ]
    }


    import time


    for retry in range(3):

        try:

            r = requests.post(
                url,
                headers=headers,
                json=data,
                timeout=180
            )

            result = r.json()


            choices = result.get("choices")

            if not choices:
                print(
                    "[GLM ERROR RESPONSE]",
                    result,
                    flush=True
                )

                return "模型返回异常，请稍后重试。"


            content = (
                choices[0]
                .get("message", {})
                .get("content")
            )


            if content:
                return content


        except Exception as e:

            print(
                f"GLM请求失败 {retry+1}/3:",
                e,
                flush=True
            )


        time.sleep(3)


    return "模型服务暂时不可用，请稍后重试。"










def get_user_name(user_id):

    try:
        token_resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": os.getenv("FEISHU_APP_ID"),
                "app_secret": os.getenv("FEISHU_APP_SECRET")
            }
        )

        token = token_resp.json()["tenant_access_token"]


        r = requests.get(
            f"https://open.feishu.cn/open-apis/contact/v3/users/{user_id}",
            headers={
                "Authorization": f"Bearer {token}"
            },
            params={
                "user_id_type": "open_id"
            }
        )

        data = r.json()

        return (
            data
            .get("data", {})
            .get("user", {})
            .get("name", user_id)
        )

    except Exception as e:
        print("获取用户失败:", e)
        return user_id


def send_text_message(chat_id, text):

    client = lark.Client.builder() \
        .app_id(os.getenv("FEISHU_APP_ID")) \
        .app_secret(os.getenv("FEISHU_APP_SECRET")) \
        .build()

    req = lark.api.im.v1.CreateMessageRequest.builder() \
        .receive_id_type("chat_id") \
        .request_body(
            lark.api.im.v1.CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(
                json.dumps({
                    "text": text
                }, ensure_ascii=False)
            )
            .build()
        ).build()

    client.im.v1.message.create(req)

def send_feishu_message(chat_id, text):

    client = lark.Client.builder() \
        .app_id(os.getenv("FEISHU_APP_ID")) \
        .app_secret(os.getenv("FEISHU_APP_SECRET")) \
        .build()

    try:
        data = json.loads(text)
    except Exception:
        data = {
            "title": "论文推荐",
            "venue": "",
            "summary": text,
            "contributions": [],
            "score": "-"
        }

    contributions = "\n".join(
        [
            f"• {x}"
            for x in data.get("contributions", [])
        ]
    )

    card_text = f"""
📚 {data.get('title','')}

🏷 {data.get('venue','')}

⭐ 推荐指数：{data.get('score','')}

**核心贡献**

{contributions}

**一句话总结**

{data.get('summary','')}
"""

    card = {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "template": "blue",
            "title": {
                "tag": "plain_text",
                "content": "📚 论文推荐"
            }
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": card_text
                }
            }
        ]
    }

    req = lark.api.im.v1.CreateMessageRequest.builder() \
        .receive_id_type("chat_id") \
        .request_body(
            lark.api.im.v1.CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(
                json.dumps(card, ensure_ascii=False)
            )
            .build()
        ).build()

    resp = client.im.v1.message.create(req)

    print("[飞书返回]", resp, flush=True)


@app.get("/")
def home():
    return {
        "status":"running"
    }


@app.get("/health")
def health():
    return {
        "ok":True
    }



@app.post("/webhook")
async def webhook(request: Request):

    data = await request.json()


    # 飞书事件去重
    event_id = (
        data.get("header", {})
        .get("event_id")
    )

    if event_id:

        if exists(event_id):

            print(
                "duplicate event:",
                event_id,
                flush=True
            )

            return {
                "code":0
            }

        save(event_id)


    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        )
    )


    # 飞书验证
    if data.get("type") == "url_verification":

        return {
            "challenge": data["challenge"]
        }



    # 收消息事件
    if data.get("header", {}).get("event_type") == "im.message.receive_v1":

        event = data["event"]


        message = event["message"]


        # 只有被@机器人时才处理
        mentions = message.get("mentions", [])

        if not mentions:
            print("ignore message without mention", flush=True)
            return {
                "code":0
            }



        # 忽略机器人自己发送的消息，避免循环
        sender_info = event.get("sender", {})

        if sender_info.get("sender_type") == "bot":
            print("ignore bot message", flush=True)
            return {
                "code":0
            }



        # 忽略机器人自己发送的消息，避免循环
        if message.get("sender", {}).get("sender_type") == "bot":
            print("ignore bot message", flush=True)
            return {
                "code":0
            }


        chat_id = message["chat_id"]


        content = json.loads(
            message["content"]
        )

        text = content.get(
            "text",
            ""
        )

        # 清理飞书mention
        text = text.replace("@_user_1", "")
        text = text.replace("@HumanGroupBot", "")
        text = text.strip()

        # 清理飞书@标记
        text = text.replace("@_user_1", "")
        text = text.replace("@HumanGroupBot", "")
        text = text.strip()



        print("用户消息:", text)


        # 收到消息立即回复
        try:

            sender_data = (
                event
                .get("sender", {})
                .get("sender_id", {})
            )

            sender = (
                sender_data.get("user_id")
                or sender_data.get("open_id")
                or sender_data.get("union_id")
                or "用户"
            )

            send_text_message(
                chat_id,
                f"⏳ 已收到请求：{text}，正在处理中..."
            )

        except Exception as e:
            print("ACK发送失败:", e)




        # ===== LLM 意图路由 =====

        from intent_router import classify_intent

        intent = classify_intent(text)

        print("Intent:", intent, flush=True)


        if intent.get("intent") == "paper_analysis":

            paper_prompt = f"""
你是计算机视觉和AI论文分析专家。

用户问题：
{text}

请严格只返回JSON。
不要Markdown。
不要解释文字。


JSON格式：

{{
"title":"",
"venue":"",
"summary":"",
"contributions":[],
"score":0,
"paper_url":"",
"code_url":"",
"background":"",
"method":"",
"experiment":"",
"limitation":"",
"insight":""
}}


字段要求：

title:
论文标题

venue:
会议和年份

summary:
一句话总结

contributions:
3-5条核心贡献

score:
推荐分数1-10

paper_url:
论文链接，必须填写

code_url:
代码链接，没有则为空

background:
研究背景

method:
核心方法和技术细节

experiment:
实验结果

limitation:
优点和局限

insight:
对数字人、视频生成、多模态方向的启发


用户问题：
{text}
"""

            answer = call_glm(paper_prompt)

            send_feishu_message(
                chat_id,
                answer
            )

            return {
                "code":0
            }



        if intent.get("intent") == "paper_daily":

            send_text_message(
                chat_id,
                "⏳ 正在准备今日论文推荐..."
            )

            from daily_paper import daily_push

            daily_push()

            return {
                "code":0
            }


        elif intent.get("intent") == "paper_weekly":

            send_text_message(
                chat_id,
                "⏳ 正在生成本周论文总结..."
            )

            from weekly_paper import weekly_push

            weekly_push()

            return {
                "code":0
            }



        if "帮助" in text or "help" in text.lower():

            help_text = """
我可以帮助你：

💬 日常交流
- 技术问题讨论
- 论文介绍
- 研究方向分析

📚 论文功能
- 推送论文
- 推荐今日论文
- 总结本周论文
- 分析指定论文

例如：
@HumanGroupBot 推送论文
@HumanGroupBot 总结本周论文
"""

            send_feishu_message(
                chat_id,
                help_text
            )

            return {
                "code":0
            }


        try:
            prompt = f"""
你是一个专业的科研助手。

请直接回答用户问题。

要求：
- 使用中文回答
- 保留关键技术细节
- 如果是论文问题，介绍论文背景、核心方法、贡献和局限
- 如果是技术问题，给出清晰解释
- 不要返回JSON
- 不要生成论文推荐卡片

用户问题：
{text}
"""

            answer = call_glm(prompt)
        except Exception as exc:
            print(f"[GLM EXCEPTION] {type(exc).__name__}: {exc}", flush=True)
            answer = "模型服务调用失败，请稍后重试。"


        print("GLM:", answer)

        send_text_message(
            chat_id,
            answer
        )

        return {
            "code":0
        }



    return {
        "code":0
    }

