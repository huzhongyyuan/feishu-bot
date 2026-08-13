from __future__ import annotations

import os
import json
import logging
import secrets
import time
import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from dotenv import load_dotenv

from intent_router import classify_intent
from event_db import init_event_db, seen_or_save
from glm_client import call_glm
from subscriptions import handle_subscription_command, init_subscriptions
from feishu_text import format_latex_for_feishu


load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("feishu_bot")

app = FastAPI()
SERVICE_START_TIME = time.time()
init_event_db()
init_subscriptions()

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



def _send_feishu_message(chat_id: str, msg_type: str, content: dict) -> None:
    from feishu_sender import get_token

    response = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={
            "Authorization": f"Bearer {get_token()}",
            "Content-Type": "application/json",
        },
        json={
            "receive_id": chat_id,
            "msg_type": msg_type,
            "content": json.dumps(content, ensure_ascii=False),
        },
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code", 0) != 0:
        raise RuntimeError(f"发送飞书消息失败：{result}")



def send_text_message(chat_id,text):
    _send_feishu_message(chat_id, "text", {"text": text})



def send_card(chat_id, data):
    if not (
        data.get("code_url")
        and data.get("llm_open_source_verified")
        and data.get("open_source_verified")
        and data.get("large_team_verified")
    ):
        raise RuntimeError(
            "论文未同时通过 LLM、仓库 API/README 与大团队核验，已取消发送"
        )
    title = format_latex_for_feishu(data.get("title") or "未命名论文")
    venue = format_latex_for_feishu(data.get("venue") or data.get("source") or "arXiv")
    source = str(data.get("source") or "arXiv")
    score = data.get("score", "-")
    summary = format_latex_for_feishu(data.get("summary") or "暂无中文总结")
    summary_en = format_latex_for_feishu(data.get("summary_en") or "")
    abstract = format_latex_for_feishu(data.get("abstract"))
    abstract_zh = format_latex_for_feishu(data.get("abstract_zh") or "")
    paper_url = str(data.get("paper_url") or data.get("url") or "")
    code_url = str(data.get("code_url") or "")
    project_url = str(data.get("project_url") or "")

    contributions = [
        format_latex_for_feishu(item)
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
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "✅ 标题、作者、摘要和链接来自 arXiv；中文总结与贡献为 AI 解读"
                }
            ]
        },
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
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "💻 **开源代码**："
                    f"[{str(data.get('code_host') or 'GitHub/GitLab')} 官方仓库"
                    + (
                        f" · ⭐ {int(data.get('repo_stars') or 0)}"
                        if int(data.get("repo_stars") or 0)
                        else ""
                    )
                    + f"]({code_url})"
                ),
            },
        },
        {
            "tag": "hr"
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**中文导读**\n{summary}"
                )
            }
        },
    ]

    verification = []
    if data.get("open_source_verified") and data.get("llm_open_source_verified"):
        verification.append("LLM 已确认论文与官方仓库对应")
    if code_url:
        host = str(data.get("code_host") or "GitHub/GitLab")
        stars = int(data.get("repo_stars") or 0)
        verification.append(f"{host} 公开仓库 API 已核验" + (f" · ⭐ {stars}" if stars else ""))
    if data.get("team_evidence"):
        verification.append(str(data["team_evidence"]))
    if verification:
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": "✅ " + "｜".join(verification)}
                ],
            }
        )

    detail_elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**核心亮点**\n" + contribution_text,
            },
        }
    ]
    if summary_en:
        detail_elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**English Guide · 英文导读**\n{summary_en}",
                },
            }
        )

    if metadata:
        detail_elements.append(
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
        detail_elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": tag_text
                }
            }
        )

    if data.get("insight"):
        detail_elements.extend(
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
                            f"{format_latex_for_feishu(data['insight'])}"
                        )
                    }
                }
            ]
        )

    if abstract_zh or abstract:
        abstract_parts = []
        if abstract_zh:
            abstract_parts.append(f"**摘要 · 中文翻译**\n{abstract_zh}")
        if abstract:
            abstract_parts.append(f"**Abstract · English Original**\n{abstract}")
        detail_elements.extend(
            [
                {
                    "tag": "hr"
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "\n\n".join(abstract_parts)
                    }
                }
            ]
        )

    elements.append(
        {
            "tag": "collapsible_panel",
            "expanded": False,
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "🔬 LLM 详细拆解与双语摘要（点击展开）",
                },
                "vertical_align": "center",
                "icon": {
                    "tag": "standard_icon",
                    "token": "down-small-ccm_outlined",
                    "size": "16px 16px",
                },
                "icon_position": "right",
                "icon_expanded_angle": -180,
            },
            "border": {"color": "grey", "corner_radius": "6px"},
            "vertical_spacing": "8px",
            "padding": "8px 10px 8px 10px",
            "elements": detail_elements,
        }
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

    _send_feishu_message(chat_id, "interactive", card)

    logger.info("飞书论文卡片发送成功 chat_id=%s", chat_id)


def _merge_verified_paper_data(paper: dict, analysis: dict) -> dict:
    """Keep model interpretation while forcing all source metadata to arXiv values."""
    result = dict(analysis or {})
    result.update(
        {
            "id": paper.get("id", ""),
            "title": paper.get("title", ""),
            "authors": list(paper.get("authors", [])),
            "institutions": list(paper.get("institutions", [])),
            "institutions_source": paper.get("institutions_source", ""),
            "contributions_original": list(
                paper.get("contributions_original", [])
            ),
            "contributions_original_source": paper.get(
                "contributions_original_source", ""
            ),
            "abstract": paper.get("abstract") or paper.get("summary", ""),
            "paper_url": paper.get("paper_url") or paper.get("url", ""),
            "source": "arXiv",
            "venue": "arXiv",
            "code_url": paper.get("code_url", ""),
            "project_url": paper.get("project_url", ""),
            "code_host": paper.get("code_host", ""),
            "repo_stars": paper.get("repo_stars", 0),
            "repo_archived": paper.get("repo_archived", False),
            "open_source_verified": paper.get("open_source_verified", False),
            "large_team_verified": paper.get("large_team_verified", False),
            "team_evidence": paper.get("team_evidence", ""),
            "llm_open_source_verified": paper.get(
                "llm_open_source_verified", False
            ),
            "llm_open_source_evidence": paper.get(
                "llm_open_source_evidence", ""
            ),
            "metadata_verified": True,
        }
    )
    return result


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


def _archive_conversation_safely(
    *,
    papers: list[dict] | None = None,
    question: str = "",
    answer: str = "",
) -> None:
    try:
        from conversation_archive import (
            archive_conversation_papers,
            archive_papers_from_conversation,
        )

        count = (
            archive_conversation_papers(papers)
            if papers is not None
            else archive_papers_from_conversation(question, answer)
        )
        if count:
            logger.info("对话论文已静默归档 count=%s", count)
    except Exception:
        # 归档失败不能影响已发送给用户的对话，后台补档器会处理已入库记录。
        logger.exception("对话论文静默归档失败")


def process_message(chat_id: str, text: str) -> None:
    try:
        from tech_news import handle_news_subscription_command

        news_subscription_response = handle_news_subscription_command(chat_id, text)
        if news_subscription_response is not None:
            send_text_message(chat_id, news_subscription_response)
            return
        subscription_response = handle_subscription_command(chat_id, text)
        if subscription_response is not None:
            send_text_message(chat_id, subscription_response)
            return

        send_text_message(chat_id, "⏳ 已收到请求，正在处理中...")
        intent = classify_intent(text)
        if _is_yuanbao_request(text) or _is_chatgpt_request(text):
            intent = {"intent": "chat"}
        logger.info("处理消息 chat_id=%s intent=%s", chat_id, intent["intent"])

        if intent["intent"] == "paper_list":
            from paper_agent import analyze_paper
            from paper_list_agent import search_topic_papers
            from paper_metadata import enrich_paper_metadata
            from paper_bilingual import enrich_bilingual_fields
            from paper_opensource import filter_open_source_large_team

            papers = filter_open_source_large_team(
                search_topic_papers(text, limit=12)
            )[:4]
            if not papers:
                send_text_message(
                    chat_id,
                    "没有找到同时通过 LLM、仓库 API 与 README 三层核验的开源大团队论文，请换一个更明确的研究主题。",
                )
                return

            send_text_message(
                chat_id,
                f"已核验 {len(papers)} 篇开源大团队论文，正在生成卡片…",
            )
            analyzed_papers = []
            for paper in papers:
                try:
                    result = enrich_bilingual_fields(
                        enrich_paper_metadata(
                            _merge_verified_paper_data(
                                paper,
                                analyze_paper(paper),
                            )
                        )
                    )
                    send_card(chat_id, result)
                    analyzed_papers.append(result)
                except Exception:
                    logger.exception("论文列表单篇分析失败")
            _archive_conversation_safely(papers=analyzed_papers)
            return

        if intent["intent"] == "paper_analysis":
            from paper_agent import analyze_paper
            from paper_metadata import enrich_paper_metadata
            from paper_bilingual import enrich_bilingual_fields
            from paper_opensource import filter_open_source_large_team
            from paper_search import search_arxiv

            papers = filter_open_source_large_team(search_arxiv(text))
            if papers:
                result = enrich_bilingual_fields(
                    enrich_paper_metadata(
                        _merge_verified_paper_data(
                            papers[0],
                            analyze_paper(papers[0]),
                        )
                    )
                )
                send_card(
                    chat_id,
                    result,
                )
                _archive_conversation_safely(papers=[result])
            else:
                send_text_message(
                    chat_id,
                    "找到的论文没有通过开源仓库三层核验，因此不发送推荐卡片。",
                )
            return

        if intent["intent"] == "paper_daily":
            from daily_paper import daily_push

            from subscriptions import get_subscription

            subscription = get_subscription(chat_id, create=True)
            daily_push(chat_id=chat_id, topics=subscription["topics"])
            return

        if intent["intent"] == "paper_weekly":
            from subscriptions import get_subscription
            from weekly_paper import weekly_push

            subscription = get_subscription(chat_id, create=True)
            weekly_push(chat_id=chat_id, topics=subscription["topics"])
            return

        answer = _chat_answer(text)
        send_text_message(chat_id, answer)
        _archive_conversation_safely(question=text, answer=answer)
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
