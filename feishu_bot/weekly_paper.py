from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from daily_paper import (
    analyze_papers_batch,
    get_hf_daily,
    parse_json_object,
    select_with_complete_images,
)
from feishu_sender import send_message, send_weekly_overview
from glm_client import call_glm
from paper_search import _query_arxiv
from paper_db import init_db, save_delivery, save_paper
from feishu_docs import create_weekly_paper_document
from paper_opensource import filter_open_source_large_team


SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_TOPICS = [
    "世界模型",
    "视频生成",
    "人体动作",
    "全景相机",
    "全景视频",
]
DOMAIN_KEYWORDS = {
    "世界模型": [
        "world model", "world-model", "embodied", "robot", "vla",
        "vision-language-action", "action model", "simulator", "planning",
    ],
    "视频生成": [
        "video generation", "video diffusion", "text-to-video", "image-to-video",
        "video model", "visual generation", "diffusion", "flow matching",
    ],
    "人体动作": [
        "human motion", "motion generation", "human animation", "avatar",
        "human reconstruction", "pose", "hand", "body", "3d human",
    ],
    "全景相机": [
        "panoramic camera", "panorama camera", "360 camera", "360-degree camera",
        "omnidirectional camera", "spherical camera", "camera array",
        "multi-camera rig", "fisheye camera", "catadioptric camera",
    ],
    "全景视频": [
        "panoramic video", "360 video", "360-degree video", "360° video",
        "omnidirectional video", "spherical video", "equirectangular video",
        "equirectangular projection", "immersive video", "6dof video",
        "viewport prediction", "spherical video quality",
    ],
}
MOTION_GENERATION_KEYWORDS = [
    "motion generation",
    "text-to-motion",
    "text to motion",
    "human motion generation",
    "motion synthesis",
    "generative motion",
    "motion editing",
]

WEEKLY_PER_CATEGORY = 3
WEEKLY_LOOKBACK_DAYS = 30
WEEKLY_CATEGORIES = {
    "motion_generation": {
        "label": "Motion Generation",
        "topics": ["人体动作生成", "Motion Generation"],
        "keywords": [
            "motion generation", "text-to-motion", "text to motion",
            "human motion generation", "motion synthesis", "generative motion",
            "motion editing", "human animation", "gesture generation",
            "dance generation", "co-speech gesture",
        ],
        "query": (
            '(all:"motion generation" OR all:"text-to-motion" OR '
            'all:"human motion generation" OR all:"motion synthesis" OR '
            'all:"motion editing" OR all:"gesture generation")'
        ),
    },
    "video": {
        "label": "Video",
        "topics": ["视频生成", "视频编辑", "Video"],
        "keywords": [
            "video generation", "text-to-video", "text to video",
            "image-to-video", "image to video", "video diffusion",
            "video editing", "video synthesis", "video model", "video understanding",
            "long video", "controllable video", "video",
        ],
        "query": (
            '(all:"video generation" OR all:"text-to-video" OR '
            'all:"image-to-video" OR all:"video diffusion" OR '
            'all:"video editing" OR all:"video model")'
        ),
    },
    "embodied_ai": {
        "label": "具身智能",
        "topics": ["具身智能", "VLA", "机器人学习"],
        "keywords": [
            "embodied ai", "embodied intelligence", "vision-language-action",
            "vision language action", "vla", "robot manipulation",
            "robot learning", "robot policy", "robotics", "humanoid robot",
            "locomotion", "navigation policy",
        ],
        "query": (
            '(all:"embodied ai" OR all:"embodied intelligence" OR '
            'all:"vision-language-action" OR all:"robot manipulation" OR '
            'all:"robot learning" OR all:"humanoid robot")'
        ),
    },
    "world_models": {
        "label": "世界模型",
        "topics": ["世界模型", "World Models"],
        "keywords": [
            "world model", "world-model", "world models", "latent dynamics",
            "dynamics model", "action-conditioned video", "action conditioned video",
            "interactive world", "world simulator", "neural simulator",
            "predictive environment", "video world model",
        ],
        "query": (
            '(all:"world model" OR all:"world-model" OR '
            'all:"latent dynamics" OR all:"world simulator" OR '
            'all:"action-conditioned video" OR all:"video world model")'
        ),
    },
}
WEEKLY_CATEGORY_ORDER = tuple(WEEKLY_CATEGORIES)

PANORAMA_QUERY = (
    '(all:"panoramic camera" OR all:"omnidirectional camera" OR '
    'all:"360-degree video" OR all:"360 video" OR all:"spherical video" OR '
    'all:"equirectangular video" OR all:"equirectangular projection")'
)


def _panorama_requested(topics: list[str]) -> bool:
    return any(
        marker in str(topic).casefold()
        for topic in topics
        for marker in ("全景", "panorama", "panoramic", "360", "omnidirectional", "spherical")
    )


def previous_week(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    this_monday = (current - timedelta(days=current.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = this_monday - timedelta(days=7)
    end = this_monday - timedelta(seconds=1)
    return start, end


def get_weekly_candidates(
    start: datetime,
    end: datetime,
    limit: int = 80,
    topics: list[str] | None = None,
) -> list[dict]:
    date_range = (
        f"submittedDate:[{start.strftime('%Y%m%d')}0000 TO "
        f"{end.strftime('%Y%m%d')}2359]"
    )
    papers = _query_arxiv(
        {
            "search_query": (
                "(cat:cs.CV OR cat:cs.AI OR cat:cs.LG OR "
                f"cat:cs.RO OR cat:cs.GR) AND {date_range}"
            ),
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    existing_ids = {paper.get("id") for paper in papers}
    # 四个固定周报方向分别检索，避免综合 cs.CV/cs.AI 最新列表挤掉小众方向。
    for config in WEEKLY_CATEGORIES.values():
        category_papers = _query_arxiv(
            {
                "search_query": f"{config['query']} AND {date_range}",
                "start": 0,
                "max_results": 40,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
        )
        for paper in category_papers:
            identity = paper.get("id") or paper.get("title", "")
            if not identity or identity in existing_ids:
                continue
            existing_ids.add(identity)
            papers.append(paper)

    if _panorama_requested(topics or DEFAULT_TOPICS):
        # 全景论文在综合 cs.CV 最新列表中的占比较低，单独查询英文术语，避免遗漏。
        panorama_papers = _query_arxiv(
            {
                "search_query": f"{PANORAMA_QUERY} AND {date_range}",
                "start": 0,
                "max_results": 30,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
        )
        existing_ids.update(paper.get("id") for paper in papers)
        papers.extend(
            paper for paper in panorama_papers if paper.get("id") not in existing_ids
        )

    hf_by_id = {paper["id"]: paper for paper in get_hf_daily()}
    for paper in papers:
        signal = hf_by_id.get(paper.get("id", ""), {})
        paper.update({key: value for key, value in signal.items() if key.startswith("hf_")})
    return papers


def _keywords(topics: list[str]) -> list[str]:
    values = []
    for topic in topics:
        values.extend(DOMAIN_KEYWORDS.get(topic, []))
        if re.search(r"[A-Za-z]", topic):
            values.append(topic.casefold())
    return list(dict.fromkeys(values))


def _heuristic_score(paper: dict, topics: list[str]) -> float:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".casefold()
    matches = sum(1 for keyword in _keywords(topics) if keyword in text)
    upvotes = max(0, int(paper.get("hf_upvotes") or 0))
    organization = bool(str(paper.get("hf_organization") or "").strip())
    return matches * 4 + math.log2(upvotes + 1) * 2 + int(organization)


def is_motion_generation_paper(paper: dict) -> bool:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".casefold()
    return any(keyword in text for keyword in MOTION_GENERATION_KEYWORDS)


def _published_datetime(paper: dict) -> datetime | None:
    value = str(paper.get("published") or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(SHANGHAI) if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI)


def weekly_category_score(
    paper: dict,
    category: str,
    preferred_start: datetime | None = None,
) -> float:
    """Deterministically score category relevance; zero means ineligible."""
    config = WEEKLY_CATEGORIES[category]
    title = str(paper.get("title") or "").casefold()
    abstract = str(paper.get("abstract") or paper.get("summary") or "").casefold()
    title_hits = sum(1 for keyword in config["keywords"] if keyword in title)
    abstract_hits = sum(1 for keyword in config["keywords"] if keyword in abstract)
    if not title_hits and not abstract_hits:
        return 0.0
    try:
        upvotes = max(0, int(paper.get("hf_upvotes") or 0))
    except (TypeError, ValueError):
        upvotes = 0
    score = title_hits * 6 + abstract_hits * 2 + math.log2(upvotes + 1)
    score += int(paper.get("institution_impact_tier") or 1) * 0.8
    score += 1.5 if paper.get("conference_verified") else 0.0
    published = _published_datetime(paper)
    if preferred_start and published and published >= preferred_start:
        score += 8.0
    return score


def ranked_category_candidates(
    papers: list[dict],
    category: str,
    preferred_start: datetime | None = None,
) -> list[dict]:
    return sorted(
        [
            paper
            for paper in papers
            if weekly_category_score(paper, category, preferred_start) > 0
        ],
        key=lambda paper: weekly_category_score(paper, category, preferred_start),
        reverse=True,
    )


def weekly_verification_shortlist(
    papers: list[dict],
    preferred_start: datetime,
    per_category: int = 18,
) -> list[dict]:
    """Build a balanced union before the expensive open-source verification."""
    result = []
    seen = set()
    for category in WEEKLY_CATEGORY_ORDER:
        for paper in ranked_category_candidates(papers, category, preferred_start)[
            :per_category
        ]:
            identity = paper.get("id") or paper.get("title", "")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            result.append(paper)
    return result


def allocate_weekly_categories(
    papers: list[dict],
    preferred_start: datetime,
    per_category: int = WEEKLY_PER_CATEGORY,
) -> dict[str, list[dict]]:
    """Allocate unique papers, filling the scarcest category first."""
    ranked = {
        category: ranked_category_candidates(papers, category, preferred_start)
        for category in WEEKLY_CATEGORY_ORDER
    }
    allocation = {category: [] for category in WEEKLY_CATEGORY_ORDER}
    used = set()
    scarcity_order = sorted(
        WEEKLY_CATEGORY_ORDER,
        key=lambda category: len(ranked[category]),
    )
    for category in scarcity_order:
        for paper in ranked[category]:
            identity = paper.get("id") or paper.get("title", "")
            if not identity or identity in used:
                continue
            allocation[category].append(paper)
            used.add(identity)
            if len(allocation[category]) >= per_category:
                break
    return allocation


def _analysis_fallback(paper: dict, category: str) -> dict:
    """Keep a verified paper when batch analysis omits it; never invent facts."""
    abstract = str(paper.get("abstract") or paper.get("summary") or "").strip()
    return {
        **paper,
        "task": "模型未返回结构化任务说明，请以摘要原文为准。",
        "main_method": "模型未返回结构化方法说明，请以论文原文为准。",
        "summary": abstract,
        "contributions": [],
        "score": 0,
        "reason": f"通过开源、团队影响力与图片完整性核验的{WEEKLY_CATEGORIES[category]['label']}论文。",
        "opinion": "建议结合 Teaser、架构图和摘要原文阅读。",
        "metadata_verified": True,
    }


def analyze_weekly_categories(
    allocation: dict[str, list[dict]],
) -> list[dict]:
    selected = []
    for category in WEEKLY_CATEGORY_ORDER:
        papers = allocation.get(category, [])
        analyzed = analyze_papers_batch(
            papers,
            topics=WEEKLY_CATEGORIES[category]["topics"],
        )
        analyzed_by_title = {
            str(paper.get("title") or ""): paper for paper in analyzed
        }
        for original in papers:
            paper = analyzed_by_title.get(str(original.get("title") or ""))
            if not paper:
                paper = _analysis_fallback(original, category)
            paper["weekly_category"] = category
            paper["weekly_category_label"] = WEEKLY_CATEGORIES[category]["label"]
            paper["card_title"] = (
                f"📚 每周论文 · {WEEKLY_CATEGORIES[category]['label']}"
            )
            selected.append(paper)
    return selected


def shortlist(papers: list[dict], topics: list[str], limit: int = 18) -> list[dict]:
    ranked = sorted(
        papers,
        key=lambda paper: _heuristic_score(paper, topics),
        reverse=True,
    )
    result = ranked[:limit]
    motion_ranked = [paper for paper in ranked if is_motion_generation_paper(paper)]
    # Motion Generation 是周报硬约束，至少让 5 篇相关候选进入模型终选。
    for paper in motion_ranked[:5]:
        if paper in result:
            continue
        if len(result) >= limit:
            result.pop()
        result.append(paper)
    return result


def analyze_weekly(papers: list[dict], topics: list[str]) -> list[dict]:
    candidates = [
        {
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", ""),
            "hf_upvotes": paper.get("hf_upvotes", 0),
            "hf_comments": paper.get("hf_comments", 0),
            "hf_organization": paper.get("hf_organization", ""),
        }
        for paper in papers
    ]
    prompt = f"""
你是严格、审慎的 AI 论文周报编辑。请从候选中选出最多 4 篇上周最值得关注的论文。
硬性约束：如果候选中存在 Motion Generation 论文，入选论文必须至少包含 1 篇真正研究 Motion Generation、Text-to-Motion、
Human Motion Generation、Motion Synthesis 或 Generative Motion Editing 的论文。
VLA、动作识别或机器人控制不能替代 Motion Generation。

关注方向：{json.dumps(topics, ensure_ascii=False)}
真实候选：{json.dumps(candidates, ensure_ascii=False)}

所有候选均已通过 LLM、仓库 API 和 README 三层开源核验。优先级：关注方向相关性；
技术贡献和实验可信度；大厂或知名实验室官方发布；Hugging Face 关注度。
兼顾主题多样性，避免入选论文高度重复。不得把搜索摘要当作论文事实，不得编造任何信息。

严格返回 JSON 对象，不要 Markdown：
{{
  "papers": [
    {{
      "title": "必须与输入标题逐字一致",
      "task": "一句话说明论文解决的具体研究任务，不得超出摘要事实",
      "main_method": "一到两句说明核心模型、模块或训练方法，只能依据摘要",
      "summary": "约220至300个中文字符的导读，依次说明研究问题、核心方法、关键结果和阅读价值，不得超出摘要事实",
      "contributions": ["可由摘要直接支持的贡献1", "贡献2"],
      "score": 0,
      "reason": "一句话说明为什么值得本周关注",
      "opinion": "一句简洁编辑观点，说明适合谁关注以及需要留意的局限；没有证据则不写局限"
    }}
  ]
}}
"""
    result = call_glm(prompt, timeout=360, web_search=True)
    payload = parse_json_object(result)
    originals = {paper.get("title", ""): paper for paper in papers}
    selected = []
    for item in payload.get("papers", []):
        if not isinstance(item, dict):
            continue
        original = originals.get(item.get("title", ""))
        if not original or any(p["title"] == item["title"] for p in selected):
            continue
        try:
            score = float(item.get("score", 0))
        except (TypeError, ValueError):
            score = 0.0
        if score > 10:
            score /= 10
        item["score"] = round(max(0.0, min(10.0, score)), 1)
        item.update(
            {
                "id": original.get("id", ""),
                "paper_url": original.get("paper_url", ""),
                "pdf_url": original.get("pdf_url", ""),
                "abstract": original.get("abstract", ""),
                "authors": list(original.get("authors", [])),
                "institutions": list(original.get("institutions", [])),
                "institutions_source": original.get("institutions_source", ""),
                "contributions_original": list(
                    original.get("contributions_original", [])
                ),
                "contributions_original_source": original.get(
                    "contributions_original_source", ""
                ),
                "published": original.get("published", ""),
                "updated": original.get("updated", ""),
                "categories": list(original.get("categories", [])),
                "source": original.get("source", "arXiv"),
                "venue": original.get("venue") or original.get("source", "arXiv"),
                "code_url": original.get("code_url", ""),
                "project_url": original.get("project_url", ""),
                "code_host": original.get("code_host", ""),
                "repo_stars": original.get("repo_stars", 0),
                "repo_archived": original.get("repo_archived", False),
                "open_source_verified": original.get("open_source_verified", False),
                "large_team_verified": original.get("large_team_verified", False),
                "team_evidence": original.get("team_evidence", ""),
                "llm_open_source_verified": original.get(
                    "llm_open_source_verified", False
                ),
                "llm_open_source_evidence": original.get(
                    "llm_open_source_evidence", ""
                ),
                "metadata_verified": True,
                "card_title": "📚 上周精选论文",
            }
        )
        selected.append(item)
        if len(selected) == 4:
            break
    if not any(is_motion_generation_paper(paper) for paper in selected):
        motion_candidates = [paper for paper in papers if is_motion_generation_paper(paper)]
        if motion_candidates:
            fallback_items = analyze_papers_batch(
                [motion_candidates[0]], topics=topics
            )
            if fallback_items:
                fallback = fallback_items[0]
            else:
                original = motion_candidates[0]
                fallback = {
                    **original,
                    "title": original.get("title", ""),
                    "summary": "Motion Generation 方向论文，详细贡献请以官方摘要为准。",
                    "contributions": [],
                    "score": 7.5,
                    "reason": "满足本周 Motion Generation 必选方向。",
                    "venue": "arXiv",
                    "code_url": original.get("code_url", ""),
                    "card_title": "📚 上周精选论文",
                }
            fallback["card_title"] = "📚 上周精选论文"
            non_motion_indexes = [
                index
                for index, paper in enumerate(selected)
                if not is_motion_generation_paper(paper)
            ]
            if non_motion_indexes:
                selected[non_motion_indexes[-1]] = fallback
            elif len(selected) < 4:
                selected.append(fallback)

    return selected[:4]


def weekly_push(
    chat_id: str | None = None,
    topics: list[str] | None = None,
    send_overview_card: bool = True,
) -> int:
    target_chat_id = (chat_id or os.getenv("FEISHU_CHAT_ID") or "").strip()
    if not target_chat_id:
        raise RuntimeError("缺少飞书推送 chat_id")
    selected_topics = topics or DEFAULT_TOPICS
    init_db()
    start, end = previous_week()
    discovery_start = start - timedelta(
        days=max(0, WEEKLY_LOOKBACK_DAYS - 7)
    )
    print(
        f"抓取周报候选: 优先 {start:%Y-%m-%d} 至 {end:%Y-%m-%d}，"
        f"不足时回补至 {discovery_start:%Y-%m-%d}",
        flush=True,
    )
    candidates = get_weekly_candidates(
        discovery_start,
        end,
        limit=120,
        topics=selected_topics,
    )
    from paper_db import get_delivered_titles

    delivered = get_delivered_titles(target_chat_id)
    candidates = [
        paper
        for paper in candidates
        if str(paper.get("title") or "") not in delivered
    ]
    print(f"周报候选数量: {len(candidates)}", flush=True)
    shortlisted = weekly_verification_shortlist(candidates, start)
    verified = filter_open_source_large_team(shortlisted)
    print(f"周报三层核验后的开源大团队候选: {len(verified)}", flush=True)
    if not verified:
        raise RuntimeError("周报没有通过三层开源核验的大团队论文")
    from paper_metadata import enrich_papers_metadata
    from paper_opensource import institution_impact

    verified = enrich_papers_metadata(verified)
    for paper in verified:
        paper.update(institution_impact(paper))

    image_complete: dict[str, list[dict]] = {}
    used = set()
    # 先处理候选较少的类别，随后 Video 等宽泛类别不能抢占稀缺论文。
    category_order = sorted(
        WEEKLY_CATEGORY_ORDER,
        key=lambda category: len(
            ranked_category_candidates(verified, category, start)
        ),
    )
    for category in category_order:
        pool = [
            paper
            for paper in ranked_category_candidates(verified, category, start)
            if (paper.get("id") or paper.get("title", "")) not in used
        ]
        chosen = select_with_complete_images(
            pool,
            pool,
            pool,
            limit=WEEKLY_PER_CATEGORY,
        )
        image_complete[category] = chosen
        used.update(paper.get("id") or paper.get("title", "") for paper in chosen)

    shortages = {
        WEEKLY_CATEGORIES[category]["label"]: WEEKLY_PER_CATEGORY - len(papers)
        for category, papers in image_complete.items()
        if len(papers) < WEEKLY_PER_CATEGORY
    }
    if shortages:
        details = "、".join(
            f"{label} 缺 {count} 篇" for label, count in shortages.items()
        )
        raise RuntimeError(
            "周报未达到四类各 3 篇的真实性/开源/完整图片门槛：" + details
        )

    selected = analyze_weekly_categories(image_complete)
    if len(selected) != WEEKLY_PER_CATEGORY * len(WEEKLY_CATEGORY_ORDER):
        raise RuntimeError("周报结构化分析未形成完整 12 篇")
    from paper_deep_reading import enrich_deep_readings

    selected = enrich_deep_readings(selected)
    from paper_bilingual import enrich_bilingual_papers

    selected = enrich_bilingual_papers(selected)
    for paper in selected:
        paper["week_start"] = start.strftime("%Y-%m-%d")
        paper["week_end"] = end.strftime("%Y-%m-%d")

    try:
        document = create_weekly_paper_document(
            selected,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            selected_topics,
            target_chat_id,
        )
        for paper in selected:
            paper["feishu_doc_url"] = document["url"]
        print(f"周报已静默归档到飞书论文库: {document['url']}", flush=True)
    except Exception as exc:
        print(f"周报飞书文档创建失败，论文卡片不受影响: {exc}", flush=True)
    print(
        "周报入选: " + " | ".join(paper.get("title", "") for paper in selected),
        flush=True,
    )

    for paper in selected:
        send_message(target_chat_id, json.dumps(paper, ensure_ascii=False))
        save_paper(paper)
        save_delivery(target_chat_id, paper.get("title", ""))
    if send_overview_card:
        send_weekly_overview(
            target_chat_id,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            [WEEKLY_CATEGORIES[key]["label"] for key in WEEKLY_CATEGORY_ORDER],
            selected,
        )
    print(f"周报发送完成: {len(selected)} 篇", flush=True)
    return len(selected)


if __name__ == "__main__":
    weekly_push(
        send_overview_card=os.getenv("WEEKLY_SKIP_OVERVIEW", "").strip().lower()
        not in {"1", "true", "yes", "on"}
    )
