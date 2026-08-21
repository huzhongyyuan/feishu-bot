import json
import os
import re
import requests
from urllib.parse import urlparse
from dotenv import load_dotenv
from feishu_text import format_latex_for_feishu

load_dotenv()


def paper_link_label(url: object) -> str:
    """Label arXiv URLs explicitly without mislabelling conference pages."""
    hostname = (urlparse(str(url or "").strip()).hostname or "").casefold()
    if hostname == "arxiv.org" or hostname.endswith(".arxiv.org"):
        return "📄 arXiv 链接"
    return "📄 官方论文页"


def compact_card_text(value, limit=220):
    """Normalize AI text for a compact, readable Feishu card block."""
    text = format_latex_for_feishu(value)
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def mini_panel(title, content, *, expanded=True):
    """Build a visible bordered mini card inside the main paper card."""
    return {
        "tag": "collapsible_panel",
        "expanded": expanded,
        "header": {
            "title": {"tag": "plain_text", "content": title},
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
        "vertical_spacing": "6px",
        "padding": "8px 10px 8px 10px",
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": content},
            }
        ],
    }


def _source_badge(source: object) -> str:
    value = str(source or "原文未明确").strip()
    if "编辑解读" in value:
        return value
    if value == "原文未明确":
        return value
    return f"原文事实 · {value}"


def sourced_items(values, *, limit=4):
    lines = []
    for index, item in enumerate(values or [], start=1):
        if isinstance(item, dict):
            text = compact_card_text(item.get("text"), limit=240)
            source = _source_badge(item.get("source"))
        else:
            text = compact_card_text(item, limit=240)
            source = "原文未明确"
        if text:
            lines.append(f"{index}. {text}\n`{source}`")
        if len(lines) >= limit:
            break
    return "\n\n".join(lines)


def method_result_items(values, *, limit=4):
    lines = []
    for index, item in enumerate(values or [], start=1):
        if not isinstance(item, dict):
            continue
        method = compact_card_text(item.get("method"), limit=150)
        result = compact_card_text(item.get("result"), limit=190)
        if not method:
            continue
        relation = f" → {result}" if result else " → 原文未明确对应结果"
        lines.append(
            f"{index}. **{method}**{relation}\n`{_source_badge(item.get('source'))}`"
        )
        if len(lines) >= limit:
            break
    return "\n\n".join(lines)


def core_insight_items(values, *, limit=2):
    lines = []
    for index, item in enumerate(values or [], start=1):
        if not isinstance(item, dict):
            continue
        finding = compact_card_text(item.get("finding"), limit=220)
        why = compact_card_text(item.get("why_it_matters"), limit=180)
        transfer = compact_card_text(item.get("transfer"), limit=180)
        if not finding:
            continue
        parts = [f"{index}. **{finding}**"]
        if why:
            parts.append(f"为什么重要：{why}")
        if transfer:
            parts.append(f"可迁移启示：{transfer}")
        parts.append(f"`{_source_badge(item.get('source'))}`")
        lines.append("\n".join(parts))
        if len(lines) >= limit:
            break
    return "\n\n".join(lines)


def deep_section(title, content):
    return {
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"**{title}**\n\n{content}"},
    }


def get_token():

    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": os.getenv("FEISHU_APP_ID"),
            "app_secret": os.getenv("FEISHU_APP_SECRET")
        },
        timeout=30,
    )
    r.raise_for_status()
    result = r.json()
    if result.get("code", 0) != 0:
        raise RuntimeError(f"获取飞书 token 失败: {result}")
    return result["tenant_access_token"]


def upload_image(token, path):
    with open(path, "rb") as image_file:
        response = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/images",
            headers={"Authorization": f"Bearer {token}"},
            data={"image_type": "message"},
            files={"image": (os.path.basename(path), image_file)},
            timeout=60,
        )
    response.raise_for_status()
    result = response.json()
    if result.get("code", 0) != 0:
        raise RuntimeError(f"飞书图片上传失败: {result}")
    return result["data"]["image_key"]



def send_message(chat_id, text):

    if not chat_id:
        raise RuntimeError("缺少 FEISHU_CHAT_ID")

    token = get_token()

    try:
        data = json.loads(text)
    except:
        data = {
            "title":"论文推荐",
            "summary":text,
            "contributions":[],
            "score":"-"
        }

    manual_no_code_exception = bool(data.get("manual_no_code_exception"))
    if not manual_no_code_exception and not (
        data.get("code_url")
        and (
            data.get("llm_open_source_verified")
            or data.get("official_source_code_verified")
        )
        and data.get("open_source_verified")
        and data.get("large_team_verified")
    ):
        raise RuntimeError(
            "论文未同时通过 LLM、仓库 API/README 与大团队核验，已取消发送"
        )

    contribution_items = [
        compact_card_text(value, limit=120)
        for value in data.get("contributions", [])
        if str(value).strip()
    ][:3]
    contributions = "\n".join(
        f"{index}. {value}"
        for index, value in enumerate(contribution_items, start=1)
    )
    original_contribution_items = [
        format_latex_for_feishu(value)
        for value in data.get("contributions_original", [])
        if str(value).strip()
    ][:5]
    original_contributions = "\n\n".join(
        f"{index}. {value}"
        for index, value in enumerate(original_contribution_items, start=1)
    )
    main_method = compact_card_text(
        data.get("main_method") or data.get("method") or "",
        limit=260,
    )

    paper_url = str(data.get("paper_url") or "").strip()
    title = format_latex_for_feishu(data.get("title", ""))
    summary = compact_card_text(data.get("summary", ""), limit=620)
    keywords = []
    raw_keywords = data.get("keywords") or []
    if isinstance(raw_keywords, str):
        raw_keywords = re.split(r"[,，、;；|]+", raw_keywords)
    for value in raw_keywords:
        keyword = compact_card_text(value, limit=36).strip(" #`·,，;；")
        if keyword and keyword.casefold() not in {
            item.casefold() for item in keywords
        }:
            keywords.append(keyword)
        if len(keywords) >= 4:
            break
    summary_en = format_latex_for_feishu(data.get("summary_en", ""))
    abstract = format_latex_for_feishu(data.get("abstract", ""))
    abstract_zh = format_latex_for_feishu(data.get("abstract_zh", ""))
    venue = format_latex_for_feishu(data.get("venue") or data.get("source") or "arXiv")
    venue_link = f"[{venue}]({paper_url})" if paper_url else venue
    authors = [str(value).strip() for value in data.get("authors", []) if str(value).strip()]
    institutions = [
        str(value).strip()
        for value in data.get("institutions", [])
        if str(value).strip()
    ]
    published = str(data.get("published") or "").strip()[:10]

    headline = f"""
**{title}**

⭐ {data.get('score','')}　　🏷 {venue_link}
"""


    source_status = (
        f"{venue} · 官方来源已核验 · 官方代码尚未发布"
        if manual_no_code_exception
        else f"{venue} · 官方来源已核验"
    )
    card = {
        "config":{
            "wide_screen_mode":True
        },
        "header":{
            "template":"blue",
            "title":{
                "tag":"plain_text",
                "content": data.get("card_title")
                or (
                    "SIGGRAPH 论文推荐"
                    if "siggraph" in str(venue).casefold()
                    else "论文推荐"
                )
            },
            "subtitle":{
                "tag":"plain_text",
                "content": source_status
            }
        },
        "elements":[
            {
                "tag":"div",
                "text":{
                    "tag":"lark_md",
                    "content":headline
                }
            }
        ]
    }

    code_url = str(data.get("code_url") or "").strip()
    code_host = str(data.get("code_host") or "GitHub/GitLab").strip()
    repo_stars = int(data.get("repo_stars") or 0)
    license_pending = str(data.get("code_license_status") or "").casefold() == "pending"
    code_label = (
        f"{code_host} 官方公开代码 · 许可证待补充"
        if license_pending
        else f"{code_host} 官方仓库"
    )
    if repo_stars:
        code_label += f" · ⭐ {repo_stars}"
    if code_url:
        card["elements"].append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"💻 **开源代码**：[{code_label}]({code_url})",
                },
            }
        )
    elif manual_no_code_exception:
        card["elements"].append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "⚠️ **代码状态**：官方尚未发布代码或模型仓库；"
                        "本卡片为用户明确允许的单篇例外，不引用第三方复现。"
                    ),
                },
            }
        )
    if int(data.get("institution_impact_tier") or 1) >= 2:
        impact_label = compact_card_text(
            data.get("institution_impact_label") or "影响力机构",
            limit=60,
        )
        impact_evidence = compact_card_text(
            data.get("institution_impact_evidence") or "",
            limit=80,
        )
        card["elements"].append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"🏛️ **影响力来源**：{impact_label}"
                        + (f" · {impact_evidence}" if impact_evidence else "")
                    ),
                },
            }
        )

    teaser_image_elements = []
    architecture_image_elements = []
    image_error = None
    try:
        from paper_media import prepare_paper_images

        images = prepare_paper_images(data)[:2]
        for index, image in enumerate(images):
            image_key = upload_image(token, image["path"])
            kind = image.get("kind") or ("teaser" if index == 0 else "architecture")
            caption = compact_card_text(
                image.get("caption") or image.get("label") or "",
                limit=260,
            )
            heading = "🖼️ Teaser · 完整原图" if kind == "teaser" else "🧠 网络 / 方法架构图 · 完整原图"
            image_elements = [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{heading}**"},
                },
                {
                    "tag": "img",
                    "img_key": image_key,
                    "alt": {
                        "tag": "plain_text",
                        "content": image["label"],
                    },
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": caption,
                        }
                    ],
                },
            ]
            if kind == "teaser":
                teaser_image_elements.extend(image_elements)
            else:
                architecture_image_elements.extend(image_elements)
    except Exception as exc:
        image_error = exc
        print(f"论文图片处理失败，停止发送纯文字卡片: {exc}", flush=True)

    if not teaser_image_elements or not architecture_image_elements:
        detail = f": {image_error}" if image_error else ""
        raise RuntimeError(
            "论文卡片缺少完整 Teaser 或网络/方法架构图，已取消发送" + detail
        )

    card["elements"].extend(teaser_image_elements)

    if keywords:
        card["elements"].append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "🏷️ **Keywords**：" + " · ".join(keywords),
                },
            }
        )

    if summary:
        card["elements"].append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**中文导读**\n\n{summary}",
                },
            }
        )

    card["elements"].extend(architecture_image_elements)

    author_text = "、".join(authors[:8]) + (" 等" if len(authors) > 8 else "")
    institution_text = "、".join(institutions[:5])
    if len(institutions) > 5:
        institution_text += " 等"
    card["elements"].append(
        mini_panel(
            "👥 作者与机构",
            f"**作者**：{author_text or '官方元数据未提供'}\n"
            f"**机构**：{institution_text or '官方 PDF 首页未明确提供'}",
        )
    )
    verification_lines = []
    if data.get("llm_open_source_verified"):
        verification_lines.append("LLM 已确认论文与官方仓库对应")
    elif data.get("official_source_code_verified"):
        verification_lines.append("arXiv 官方 Code 链接已确认论文与仓库对应")
    if data.get("open_source_verified") and data.get("code_url"):
        host = str(data.get("code_host") or "GitHub/GitLab")
        stars = int(data.get("repo_stars") or 0)
        verification_lines.append(
            f"{host} 公开仓库 API + README 已核验"
            + (f" · ⭐ {stars}" if stars else "")
        )
    if data.get("team_evidence"):
        verification_lines.append(str(data.get("team_evidence")))
    if verification_lines:
        card["elements"].append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "✅ " + "｜".join(verification_lines),
                    }
                ],
            }
        )
    if original_contributions:
        card["elements"].append(
            mini_panel(
                "📝 Contributions · 英文原文",
                original_contributions,
                expanded=False,
            )
        )

    deep_elements = []
    research_question = data.get("research_question") or {}
    if isinstance(research_question, dict) and research_question.get("text"):
        question_content = (
            compact_card_text(research_question.get("text"), limit=280)
            + f"\n\n`{_source_badge(research_question.get('source'))}`"
        )
        deep_elements.append(deep_section("研究问题", question_content))
    if contributions:
        deep_elements.append(deep_section("核心贡献 · 中文", contributions))
    if main_method:
        deep_elements.append(deep_section("核心方法", main_method))
    core_insights = core_insight_items(data.get("core_insights"))
    background = sourced_items(data.get("background"))
    method_map = method_result_items(data.get("method_result_map"))
    key_results = sourced_items(data.get("key_results"))
    evidence_chain = sourced_items(data.get("evidence_chain"))
    discussion = sourced_items(data.get("discussion_highlights"))
    limitations = sourced_items(data.get("limitations"))
    writing_notes = sourced_items(data.get("writing_notes"))
    if core_insights:
        deep_elements.append(deep_section("先看结论 · 可带走的 Insight", core_insights))
    if background:
        deep_elements.append(deep_section("研究背景与动机", background))
    if method_map:
        deep_elements.append(deep_section("方法 ↔ 实验结果", method_map))
    if key_results:
        deep_elements.append(deep_section("关键实验结果", key_results))
    if evidence_chain:
        deep_elements.append(deep_section("证据链与论证顺序", evidence_chain))
    if discussion or limitations:
        discussion_text = discussion
        if limitations:
            discussion_text += ("\n\n" if discussion_text else "") + "**作者明确局限**\n\n" + limitations
        deep_elements.append(deep_section("讨论：亮点与不足", discussion_text))
    if writing_notes:
        deep_elements.append(deep_section("写作拆解", writing_notes))
    if deep_elements:
        card["elements"].append(
            {
                "tag": "collapsible_panel",
                "expanded": False,
                "header": {
                    "title": {"tag": "plain_text", "content": "🔬 LLM 深度拆解（点击展开）"},
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
                "elements": deep_elements,
            }
        )

    source_label = str(data.get("source") or venue or "官方论文来源")
    verified_lines = [f"来源：{source_label}"]
    if authors:
        verified_lines.append(f"作者：{author_text}")
    if institutions:
        verified_lines.append(f"机构：{institution_text}")
    if published:
        verified_lines.append(f"提交日期：{published}")
    detail_elements = [
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "✅ " + "｜".join(verified_lines),
                }
            ],
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
    if abstract_zh:
        detail_elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**摘要 · 中文翻译**\n{abstract_zh}",
                },
            }
        )
    if abstract:
        detail_elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**Abstract · English Original**\n{abstract}",
                },
            }
        )
    if paper_url:
        detail_elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**论文官方链接**\n{paper_url}",
                },
            }
        )

    card["elements"].append(
        {
            "tag": "collapsible_panel",
            "expanded": False,
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "查看中英导读、双语摘要与更多信息",
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
            "border": {"color": "grey", "corner_radius": "5px"},
            "vertical_spacing": "8px",
            "padding": "8px 8px 8px 8px",
            "elements": detail_elements,
        }
    )

    actions = []
    if paper_url:
        actions.append({
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": paper_link_label(paper_url),
            },
            "type": "primary",
            "url": paper_url,
        })
    if data.get("code_url"):
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "💻 查看代码"},
            "url": data["code_url"],
        })
    if data.get("feishu_doc_url"):
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📚 图文深度解析"},
            "url": data["feishu_doc_url"],
        })
    if actions:
        card["elements"].append({"tag": "action", "actions": actions})


    r=requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",

        headers={
            "Authorization":f"Bearer {token}",
            "Content-Type":"application/json"
        },

        json={
            "receive_id":chat_id,
            "msg_type":"interactive",
            "content":json.dumps(card,ensure_ascii=False)
        },
        timeout=30,
    )

    r.raise_for_status()
    result = r.json()
    if result.get("code", 0) != 0:
        raise RuntimeError(f"飞书发送失败: {result}")
    print("[飞书返回] 发送成功", flush=True)


def send_weekly_overview(chat_id, start_date, end_date, topics, papers):
    """Send one compact overview before the individual weekly paper cards."""
    if not chat_id:
        raise RuntimeError("缺少 FEISHU_CHAT_ID")

    token = get_token()
    topic_text = "、".join(topics) or "综合人工智能"
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "indigo",
            "title": {"tag": "plain_text", "content": "🗓️ 上周值得关注的论文"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"{start_date} — {end_date} · 元数据已核验",
            },
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**关注方向**：{topic_text}",
                },
            },
        ],
    }

    grouped = {}
    for paper in papers:
        label = str(
            paper.get("weekly_category_label") or "其他"
        ).strip()
        grouped.setdefault(label, []).append(paper)

    # 12 篇周报总览只保留四类目录，完整图文内容由后续单篇卡片承载，
    # 避免飞书卡片元素过多、加载缓慢或超过平台限制。
    for label, category_papers in grouped.items():
        lines = []
        for index, paper in enumerate(category_papers, start=1):
            title = format_latex_for_feishu(paper.get("title"))
            paper_url = str(paper.get("paper_url") or "").strip()
            code_url = str(paper.get("code_url") or "").strip()
            title_link = f"[{title}]({paper_url})" if paper_url else title
            code_link = f" · [代码]({code_url})" if code_url else ""
            lines.append(f"{index}. {title_link}{code_link}")
        card["elements"].append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{label} · {len(category_papers)} 篇**\n" + "\n".join(lines),
                },
            }
        )

    card["elements"].append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": (
                        "筛选依据：主题相关性、技术贡献、实验可信度、"
                        "Hugging Face 关注度与官方开源信号。"
                    ),
                }
            ],
        }
    )
    response = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        },
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code", 0) != 0:
        raise RuntimeError(f"飞书周报总览发送失败: {result}")
    print("[飞书返回] 周报总览发送成功", flush=True)
