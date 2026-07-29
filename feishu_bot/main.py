from fastapi import FastAPI, Request
import requests
import json
import os
from dotenv import load_dotenv
import lark_oapi as lark


load_dotenv()

app = FastAPI()


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

    r = requests.post(
        url,
        headers=headers,
        json=data,
        timeout=60
    )

    result = r.json()

    return result["choices"][0]["message"]["content"]





def send_feishu_message(chat_id, text):

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
                })
            )
            .build()
        ).build()

    client.im.v1.message.create(req)

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

        chat_id = message["chat_id"]


        content = json.loads(
            message["content"]
        )

        text = content.get(
            "text",
            ""
        )


        print("用户消息:", text)


        answer = call_glm(text)


        print("GLM:", answer)

        send_feishu_message(
            chat_id,
            answer
        )

        return {
            "code":0
        }



    return {
        "code":0
    }

