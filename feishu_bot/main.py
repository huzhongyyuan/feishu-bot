import os
import json
import requests
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import lark_oapi as lark

from intent_router import classify_intent


load_dotenv()


app = FastAPI()


PROCESSED_EVENTS = set()


ZAI_API_KEY = os.getenv("ZAI_API_KEY")


def call_glm(text):

    r = requests.post(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        headers={
            "Content-Type":"application/json",
            "Authorization":f"Bearer {ZAI_API_KEY}"
        },
        json={
            "model":"glm-4.5",
            "messages":[
                {
                    "role":"user",
                    "content":text
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



def get_client():

    return (
        lark.Client.builder()
        .app_id(
            os.getenv("FEISHU_APP_ID")
        )
        .app_secret(
            os.getenv("FEISHU_APP_SECRET")
        )
        .build()
    )



def send_text_message(chat_id,text):

    client=get_client()

    req=(
        lark.api.im.v1.CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            lark.api.im.v1.CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(
                json.dumps(
                    {
                        "text":text
                    },
                    ensure_ascii=False
                )
            )
            .build()
        )
        .build()
    )

    client.im.v1.message.create(req)



def send_card(chat_id,data):

    client=get_client()

    card={
        "config":{
            "wide_screen_mode":True
        },
        "elements":[
            {
                "tag":"div",
                "text":{
                    "tag":"lark_md",
                    "content":
                    f"""
📚 {data.get('title','')}

🏷 {data.get('venue','')}

⭐ 推荐指数：
{data.get('score','')}

一句话总结：
{data.get('summary','')}


核心贡献：

{chr(10).join(
    ['• '+x for x in data.get('contributions',[])]
)}


Abstract:

{data.get('abstract', '')}


🔗 Paper:
{data.get('paper_url','')}

💻 Code:
{data.get('code_url','')}
"""
                }
            }
        ]
    }


    req=(
        lark.api.im.v1.CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            lark.api.im.v1.CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(
                json.dumps(
                    card,
                    ensure_ascii=False
                )
            )
            .build()
        )
        .build()
    )

    client.im.v1.message.create(req)



@app.post("/webhook")
async def webhook(request:Request):

    data=await request.json()


    if data.get("type")=="url_verification":

        return {
            "challenge":data["challenge"]
        }



    header=data.get("header",{})

    event_id=header.get(
        "event_id"
    )

    if event_id:

        if event_id in PROCESSED_EVENTS:
            return {
                "code":0
            }

        PROCESSED_EVENTS.add(
            event_id
        )



    if header.get(
        "event_type"
    )!="im.message.receive_v1":

        return {
            "code":0
        }



    event=data["event"]

    message=event["message"]


    if not message.get("mentions"):

        return {
            "code":0
        }



    chat_id=message["chat_id"]


    content=json.loads(
        message["content"]
    )

    text=content.get(
        "text",
        ""
    )


    text=text.replace(
        "@_user_1",
        ""
    )

    text=text.replace(
        "@HumanGroupBot",
        ""
    ).strip()



    send_text_message(
        chat_id,
        "⏳ 已收到请求，正在处理中..."
    )


    intent=classify_intent(text)


    print(
        "INTENT:",
        intent,
        flush=True
    )


    if intent["intent"]=="paper_analysis":

        from paper_search import search_arxiv
        from paper_agent import analyze_paper


        papers=search_arxiv(
            text
        )


        if papers:

            result=analyze_paper(
                papers[0]
            )

            send_card(
                chat_id,
                result
            )

        else:

            send_text_message(
                chat_id,
                "没有找到相关论文"
            )


        return {
            "code":0
        }



    if intent["intent"]=="paper_daily":

        from daily_paper import daily_push

        daily_push()

        return {
            "code":0
        }



    answer=call_glm(text)

    send_text_message(
        chat_id,
        answer
    )


    return {
        "code":0
    }



@app.get("/")
def home():

    return {
        "status":"running"
    }
