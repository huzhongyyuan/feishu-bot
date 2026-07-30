import os
import json
import logging
import secrets
import time
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from dotenv import load_dotenv
import lark_oapi as lark

from intent_router import classify_intent
from event_db import init_event_db, seen_or_save
from glm_client import call_glm


load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("feishu_bot")

app = FastAPI()
SERVICE_START_TIME = time.time()
init_event_db()

REQUIRED_CONFIG = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "ZAI_API_KEY",
)
missing_config = [key for key in REQUIRED_CONFIG if not os.getenv(key)]
if missing_config:
    raise RuntimeError("缺少必要配置：" + ", ".join(missing_config))

if not os.getenv("FEISHU_VERIFICATION_TOKEN"):
    logger.warning(
        "未配置 FEISHU_VERIFICATION_TOKEN；Webhook 暂时只依赖随机公网地址保护"
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


def _ensure_lark_success(response, action: str) -> None:
    if hasattr(response, "success") and not response.success():
        code = getattr(response, "code", "unknown")
        msg = getattr(response, "msg", "unknown")
        raise RuntimeError(f"{action}失败：code={code}, msg={msg}")



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

    response = client.im.v1.message.create(req)
    _ensure_lark_success(response, "发送飞书文本消息")



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
    _ensure_lark_success(response, "发送飞书论文卡片")

    logger.info("飞书论文卡片发送成功 chat_id=%s", chat_id)


def _verify_webhook_token(data: dict) -> None:
    expected = os.getenv("FEISHU_VERIFICATION_TOKEN")
    if not expected:
        return

    received = str(
        data.get("token")
        or data.get("header", {}).get("token")
        or ""
    )
    if not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=403, detail="invalid verification token")


def _clean_message_text(message: dict) -> str:
    try:
        content = json.loads(message.get("content") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("飞书文本消息 content 不是合法 JSON") from exc

    text = str(content.get("text") or "")
    for mention in message.get("mentions") or []:
        key = mention.get("key")
        if key:
            text = text.replace(key, " ")

    return (
        text.replace("@_user_1", " ")
        .replace("@HumanGroupBot", " ")
        .strip()
    )


def _is_yuanbao_request(text: str) -> bool:
    return "元宝" in text


def _is_chatgpt_request(text: str) -> bool:
    return "gpt" in text.lower()


def _strip_chatgpt_command(text: str) -> str:
    prefixes = (
        "问ChatGPT",
        "问chatgpt",
        "问GPT",
        "问gpt",
        "ChatGPT：",
        "ChatGPT:",
        "chatgpt：",
        "chatgpt:",
        "GPT：",
        "GPT:",
        "gpt：",
        "gpt:",
    )
    stripped = text.strip()
    for prefix in prefixes:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


def _chat_answer(text: str) -> str:
    provider = os.getenv("CHAT_PROVIDER", "auto").strip().lower()
    yuanbao_prefixes = ("问元宝", "元宝：", "元宝:")
    explicit_yuanbao = _is_yuanbao_request(text)
    explicit_chatgpt = _is_chatgpt_request(text) and not explicit_yuanbao
    question = text

    if explicit_yuanbao:
        for prefix in yuanbao_prefixes:
            if question.startswith(prefix):
                question = question[len(prefix):].strip()
                break

    if explicit_chatgpt:
        from chatgpt_agent import ChatGPTWebError, ask_chatgpt

        try:
            answer = ask_chatgpt(_strip_chatgpt_command(text))
            return "【ChatGPT 网页】\n\n" + answer
        except ChatGPTWebError as exc:
            logger.warning("ChatGPT 网页调用不可用: %s", exc)
            return f"【ChatGPT 网页】\n\n{exc}"

    use_yuanbao = provider in {"yuanbao", "both"} or explicit_yuanbao
    if not use_yuanbao:
        return call_glm(question)

    try:
        from yuanbao_agent import ask_yuanbao

        yuanbao_answer = ask_yuanbao(question)
    except Exception:
        logger.exception("元宝调用失败，回退 GLM")
        return "元宝暂时不可用，已切换 GLM：\n\n" + call_glm(question)

    if provider == "both" and not explicit_yuanbao:
        glm_answer = call_glm(question)
        return (
            "【元宝】\n"
            + yuanbao_answer
            + "\n\n【GLM】\n"
            + glm_answer
        )

    model = os.getenv("YUANBAO_MODEL", "deepseek").strip().lower()
    model_label = "DeepSeek" if model in {"deepseek", "deep_seek"} else "混元"
    deep_label = (
        " · 深度思考"
        if os.getenv("YUANBAO_DEEP_THINKING", "true").strip().lower()
        in {"1", "true", "yes", "on"}
        else ""
    )
    return f"【元宝 · {model_label}{deep_label}】\n\n{yuanbao_answer}"


def process_message(chat_id: str, text: str) -> None:
    try:
        send_text_message(chat_id, "⏳ 已收到请求，正在处理中...")
        intent = classify_intent(text)
        if _is_yuanbao_request(text) or _is_chatgpt_request(text):
            intent = {"intent": "chat"}
        logger.info("处理消息 chat_id=%s intent=%s", chat_id, intent["intent"])

        if intent["intent"] == "paper_list":
            from paper_agent import analyze_paper
            from paper_list_agent import search_topic_papers

            papers = search_topic_papers(text, limit=4)
            if not papers:
                send_text_message(
                    chat_id,
                    "没有检索到相关 arXiv 论文，请换一个更明确的研究主题。",
                )
                return

            send_text_message(
                chat_id,
                f"检索到 {len(papers)} 篇相关 arXiv 论文，正在生成卡片…",
            )
            for paper in papers:
                try:
                    result = analyze_paper(paper)
                    result["abstract"] = ""
                    result["paper_url"] = (
                        paper.get("paper_url")
                        or paper.get("url")
                        or result.get("paper_url", "")
                    )
                    send_card(chat_id, result)
                except Exception:
                    logger.exception("论文列表单篇分析失败")
            return

        if intent["intent"] == "paper_analysis":
            from paper_agent import analyze_paper
            from paper_search import search_arxiv

            papers = search_arxiv(text)
            if papers:
                send_card(chat_id, analyze_paper(papers[0]))
            else:
                send_text_message(chat_id, "没有找到相关论文")
            return

        if intent["intent"] == "paper_daily":
            from daily_paper import daily_push

            if not os.getenv("FEISHU_CHAT_ID"):
                send_text_message(
                    chat_id,
                    "每日主动推送尚未配置 FEISHU_CHAT_ID。",
                )
                return
            daily_push()
            return

        send_text_message(chat_id, _chat_answer(text))
    except Exception:
        logger.exception("后台消息处理失败 chat_id=%s", chat_id)
        try:
            send_text_message(chat_id, "处理失败，请稍后重试或联系管理员查看日志。")
        except Exception:
            logger.exception("发送失败提示也失败 chat_id=%s", chat_id)


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

    _verify_webhook_token(data)

    if data.get("type") == "url_verification":
        challenge = data.get("challenge")
        if not challenge:
            raise HTTPException(status_code=400, detail="missing challenge")
        return {"challenge": challenge}

    header = data.get("header") or {}
    if header.get("event_type") != "im.message.receive_v1":
        return {"code": 0}

    event_id = header.get("event_id", "")
    if event_id and seen_or_save(event_id):
        logger.info("忽略重复事件 event_id=%s", event_id)
        return {"code": 0}

    event = data.get("event") or {}
    message = event.get("message") or {}
    sender = event.get("sender") or {}
    sender_type = sender.get("sender_type", "")
    if sender_type in {"bot", "app"}:
        return {"code": 0}

    sender_id = sender.get("sender_id") or {}
    sender_open_id = sender_id.get("open_id", "")
    allowed_open_ids = {
        value.strip()
        for value in os.getenv("FEISHU_ALLOWED_OPEN_IDS", "").split(",")
        if value.strip()
    }
    if allowed_open_ids and sender_open_id not in allowed_open_ids:
        logger.info("忽略非白名单用户 sender_open_id=%s", sender_open_id)
        return {"code": 0}

    if message.get("message_type") != "text":
        return {"code": 0}

    try:
        message_time = int(message.get("create_time", "0")) / 1000
    except (TypeError, ValueError):
        message_time = 0
    if message_time < SERVICE_START_TIME - 3:
        logger.info("忽略服务启动前的历史消息 create_time=%s", message.get("create_time"))
        return {"code": 0}

    if not message.get("mentions"):
        return {"code": 0}

    chat_id = message.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=400, detail="missing chat_id")

    try:
        text = _clean_message_text(message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not text:
        return {"code": 0}

    background_tasks.add_task(process_message, chat_id, text)
    return {"code": 0}



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
