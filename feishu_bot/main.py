import os
import json
import time
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import lark_oapi as lark

from intent_router import classify_intent
from event_db import init_event_db, seen_or_save
from glm_client import call_glm


load_dotenv()


app = FastAPI()
SERVICE_START_TIME = time.time()
init_event_db()




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



def send_card(chat_id, data):

    client = get_client()

    title = str(data.get("title") or "未命名论文")
    venue = str(data.get("venue") or data.get("source") or "arXiv")
    source = str(data.get("source") or "arXiv")
    score = data.get("score", "-")
    summary = str(data.get("summary") or "暂无中文总结")
    abstract = str(data.get("abstract") or "")
    paper_url = str(data.get("paper_url") or data.get("url") or "")
    code_url = str(data.get("code_url") or "")
    project_url = str(data.get("project_url") or "")

    contributions = [
        str(item).strip()
        for item in data.get("contributions", [])
        if str(item).strip()
    ][:4]

    tags = [
        str(item).strip()
        for item in data.get("tags", [])
        if str(item).strip()
    ][:5]

    modules = [
        str(item).strip()
        for item in data.get("modules", [])
        if str(item).strip()
    ][:5]

    try:
        score_value = float(score)

        if score_value >= 9:
            score_label = "强烈推荐"
        elif score_value >= 8:
            score_label = "推荐"
        elif score_value >= 7:
            score_label = "值得关注"
        else:
            score_label = "一般"

        score_text = f"{score_value:.1f} · {score_label}"

    except (TypeError, ValueError):
        score_text = "待评估"

    if ":" in title:
        short_title, subtitle = title.split(":", 1)
        short_title = short_title.strip()
        subtitle = subtitle.strip()
    else:
        short_title = title
        subtitle = ""

    contribution_text = "\n".join(
        f"• {item}"
        for item in contributions
    ) or "• 暂无结构化贡献信息"

    metadata = []

    if data.get("dataset"):
        metadata.append(f"Dataset：{data['dataset']}")

    if data.get("backbone"):
        metadata.append(f"Backbone：{data['backbone']}")

    if modules:
        metadata.append("Modules：" + " · ".join(modules))

    tag_text = "  ".join(
        f"`{tag}`"
        for tag in tags
    )

    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**{short_title}**"
                    + (f"\n{subtitle}" if subtitle else "")
                )
            }
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"⭐ **{score_text}**"
                    f"　　🏷 {venue}"
                )
            }
        },
        {
            "tag": "hr"
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**一句话总结**\n{summary}"
                )
            }
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "**核心亮点**\n"
                    f"{contribution_text}"
                )
            }
        }
    ]

    if metadata:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "**论文速览**\n"
                        + "\n".join(metadata)
                    )
                }
            }
        )

    if tag_text:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": tag_text
                }
            }
        )

    if data.get("insight"):
        elements.extend(
            [
                {
                    "tag": "hr"
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            "**对当前研究的启发**\n"
                            f"{data['insight']}"
                        )
                    }
                }
            ]
        )

    if abstract:
        elements.extend(
            [
                {
                    "tag": "hr"
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            "**Abstract · Original**\n"
                            f"{abstract}"
                        )
                    }
                }
            ]
        )

    actions = []

    if paper_url:
        actions.append(
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "📄 阅读论文"
                },
                "type": "primary",
                "url": paper_url
            }
        )

    if project_url:
        actions.append(
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "🌐 项目主页"
                },
                "type": "default",
                "url": project_url
            }
        )

    if code_url:
        actions.append(
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "💻 查看代码"
                },
                "type": "default",
                "url": code_url
            }
        )

    if actions:
        elements.append(
            {
                "tag": "action",
                "actions": actions
            }
        )

    if not code_url:
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "💻 代码：暂未公开"
                    }
                ]
            }
        )

    card = {
        "config": {
            "wide_screen_mode": True,
            "enable_forward": True
        },
        "header": {
            "template": "blue",
            "title": {
                "tag": "plain_text",
                "content": "论文推荐"
            },
            "subtitle": {
                "tag": "plain_text",
                "content": source
            }
        },
        "elements": elements
    }

    req = (
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

    response = client.im.v1.message.create(req)

    print(
        "[飞书论文卡片返回]",
        response,
        flush=True
    )


@app.post("/webhook")
async def webhook(request:Request):

    data=await request.json()


    if data.get("type")=="url_verification":

        return {
            "challenge":data["challenge"]
        }



    header=data.get("header",{})

    event_id = header.get("event_id", "")

    if event_id and seen_or_save(event_id):
        print("忽略重复事件:", event_id, flush=True)
        return {
            "code": 0
        }

    if header.get(
        "event_type"
    )!="im.message.receive_v1":

        return {
            "code":0
        }



    event=data["event"]

    message=event["message"]

    # 忽略机器人或应用自身消息
    sender_type = event.get("sender", {}).get("sender_type", "")
    if sender_type in {"bot", "app"}:
        print("忽略非用户消息:", sender_type, flush=True)
        return {
            "code": 0
        }

    # 只处理文本消息
    if message.get("message_type") != "text":
        print("忽略非文本消息", flush=True)
        return {
            "code": 0
        }

    # 忽略重启后重新投递的历史消息
    create_time = message.get("create_time", "0")
    try:
        message_time = int(create_time) / 1000
    except (TypeError, ValueError):
        message_time = 0

    # 只处理本次服务启动之后产生的新消息
    if message_time < SERVICE_START_TIME - 3:
        print("忽略服务启动前的历史消息:", create_time, flush=True)
        return {
            "code": 0
        }



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


    if intent["intent"]=="paper_list":

        from paper_list_agent import search_topic_papers
        from paper_agent import analyze_paper

        papers = search_topic_papers(
            text,
            limit=4
        )

        if not papers:
            send_text_message(
                chat_id,
                "没有检索到相关 arXiv 论文，请换一个更明确的研究主题。"
            )
            return {
                "code": 0
            }

        send_text_message(
            chat_id,
            f"检索到 {len(papers)} 篇相关 arXiv 论文，正在生成卡片…"
        )

        for paper in papers:
            try:
                result = analyze_paper(paper)

                # 多论文推荐使用紧凑卡片，避免全文摘要占满群聊
                result["abstract"] = ""
                result["paper_url"] = (
                    paper.get("paper_url")
                    or paper.get("url")
                    or result.get("paper_url", "")
                )

                send_card(
                    chat_id,
                    result
                )

            except Exception as exc:
                print("[PAPER LIST] analyze failed:", exc, flush=True)

        return {
            "code": 0
        }


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


@app.get("/health")
def health():
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - SERVICE_START_TIME, 1),
    }
