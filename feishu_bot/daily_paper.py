from feishu_sender import send_message as send_feishu_message
from automation_llm import call_automation_llm as call_glm
from paper_db import (
    get_delivered_titles,
    init_db,
    paper_delivered,
    save_delivery,
    save_paper,
)
from paper_ranker import CONFIG
from dotenv import load_dotenv
import os
import json
import requests
import re
import time
from paper_search import _query_arxiv
from datetime import datetime, timedelta, timezone


load_dotenv()


LIBRARY = "paper_library.json"
RECENT_LOOKBACK_DAYS = 30
ARXIV_RETRY_SECONDS = 2 * 60
HF_DAILY_URLS = (
    "https://huggingface.co/api/daily_papers",
    "https://hf-mirror.com/api/daily_papers",
)
HF_DAILY_HOT_LIMIT = 20
PANORAMA_QUERY = (
    '(all:"panoramic camera" OR all:"omnidirectional camera" OR '
    'all:"360-degree video" OR all:"360 video" OR all:"spherical video" OR '
    'all:"equirectangular video" OR all:"equirectangular projection")'
)
MAJOR_AI_QUERY = (
    '(all:"OpenAI" OR all:"Anthropic" OR all:"DeepSeek" OR all:"DeepMind" OR '
    'all:"Google" OR all:"Meta" OR all:"Microsoft" OR all:"NVIDIA" OR '
    'all:"Adobe" OR all:"Apple" OR all:"Amazon" OR all:"ByteDance" OR '
    'all:"Tencent" OR all:"Alibaba" OR all:"Baidu" OR all:"Salesforce") AND '
    '(cat:cs.AI OR cat:cs.CL OR cat:cs.CV OR cat:cs.LG OR cat:cs.RO OR '
    'cat:cs.CR OR cat:cs.GR)'
)
PANORAMA_MARKERS = (
    "panorama",
    "panoramic",
    "360-degree",
    "360°",
    "360 video",
    "omnidirectional",
    "spherical video",
    "equirectangular",
    "fisheye camera",
    "catadioptric camera",
)
OPEN_SOURCE_FIELDS = (
    "code_url",
    "code_host",
    "repo_stars",
    "repo_archived",
    "open_source_verified",
    "large_team_verified",
    "team_evidence",
    "llm_open_source_verified",
    "llm_open_source_evidence",
    "official_source_code_verified",
    "institution_impact_tier",
    "institution_impact_label",
    "institution_impact_evidence",
)


def _candidate_identity(paper: dict) -> str:
    """Return the same stable identity used while merging candidate sources."""
    return str(
        paper.get("id")
        or paper.get("paper_url")
        or paper.get("title")
        or ""
    ).strip()


def _official_venue_fallback_candidates(
    candidates: list[dict],
    *,
    attempted_identities=(),
    delivered_titles=(),
) -> list[dict]:
    """Keep untried, undelivered papers verified by an official venue list."""
    attempted = {str(value).strip() for value in attempted_identities if value}
    delivered = {str(value).strip().casefold() for value in delivered_titles if value}
    result = []
    seen = set()
    for paper in candidates:
        if not (
            paper.get("conference_verified")
            or paper.get("journal_verified")
        ):
            continue
        identity = _candidate_identity(paper)
        title = str(paper.get("title") or "").strip()
        if (
            not identity
            or identity in attempted
            or identity in seen
            or not title
            or title.casefold() in delivered
        ):
            continue
        seen.add(identity)
        result.append(paper)
    return result


def _verify_candidate_batches(
    candidates: list[dict],
    verifier,
    *,
    batch_size: int = 16,
    target_count: int = 1,
) -> tuple[list[dict], list[dict]]:
    """Verify fallback candidates in bounded batches until one can be sent."""
    verified = []
    attempted = []
    size = max(1, int(batch_size))
    target = max(1, int(target_count))
    for start in range(0, len(candidates), size):
        batch = candidates[start : start + size]
        attempted.extend(batch)
        verified.extend(verifier(batch))
        if len(verified) >= target:
            break
    return verified, attempted


def _fetch_expanded_official_candidates(topics, delivered_titles) -> list[dict]:
    """Read a broader official conference/journal pool for daily fallback."""
    fetchers = []
    try:
        from conference_papers import get_conference_candidates

        fetchers.append(
            (
                "会议官方扩展池",
                lambda: get_conference_candidates(
                    topics,
                    exclude_titles=delivered_titles,
                    limit=8,
                ),
            )
        )
    except Exception as exc:
        print(f"会议官方扩展池加载失败: {exc}", flush=True)
    try:
        from tpami_source import get_tpami_candidates

        fetchers.append(
            (
                "TPAMI 扩展池",
                lambda: get_tpami_candidates(
                    topics,
                    exclude_titles=delivered_titles,
                    limit=10,
                ),
            )
        )
    except Exception as exc:
        print(f"TPAMI 扩展池加载失败: {exc}", flush=True)
    try:
        from science_robotics_source import get_science_robotics_candidates

        fetchers.append(
            (
                "Science Robotics 扩展池",
                lambda: get_science_robotics_candidates(
                    topics,
                    exclude_titles=delivered_titles,
                    limit=10,
                ),
            )
        )
    except Exception as exc:
        print(f"Science Robotics 扩展池加载失败: {exc}", flush=True)
    try:
        from priority_journal_source import get_priority_journal_candidates

        fetchers.append(
            (
                "T-RO / RA-L / TOG 扩展池",
                lambda: get_priority_journal_candidates(
                    topics,
                    exclude_titles=delivered_titles,
                    limit=10,
                ),
            )
        )
    except Exception as exc:
        print(f"优先期刊扩展池加载失败: {exc}", flush=True)

    papers = []
    seen = set()
    for label, fetch in fetchers:
        try:
            values = fetch()
            print(f"{label}: {len(values)}", flush=True)
        except Exception as exc:
            print(f"{label}获取失败，继续尝试其他官方列表: {exc}", flush=True)
            continue
        for paper in values:
            identity = _candidate_identity(paper)
            if identity and identity not in seen:
                seen.add(identity)
                papers.append(paper)
    return papers


def get_official_tech_reports() -> list[dict]:
    """Return reports verified through generic first-party cross-links."""
    from official_report_source import discover_official_reports

    return discover_official_reports(get=requests.get)


def published_within_lookback(paper, days=RECENT_LOOKBACK_DAYS):
    """Only allow arXiv papers published within the configured recent window."""
    value = str(paper.get("published") or "").strip()
    if not value:
        return False
    try:
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return now - timedelta(days=days) <= published <= now + timedelta(days=1)


def parse_json_object(value):
    """Parse model JSON even when it is wrapped in a Markdown code fence."""
    text = (value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].strip()

    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1], strict=False)
        raise


def load_library():

    if not os.path.exists(LIBRARY):
        return []

    with open(
        LIBRARY,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f).get("papers", [])



def save_library(papers):

    with open(
        LIBRARY,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            {
                "papers": papers
            },
            f,
            ensure_ascii=False,
            indent=2
        )





def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _rank_hf_daily_items(payload, limit=HF_DAILY_HOT_LIMIT):
    """Keep the newest HF Daily issue and rank it by community attention."""
    items = [item for item in payload if isinstance(item, dict) and item.get("paper")]
    dates = [
        str(item["paper"].get("submittedOnDailyAt") or "")[:10]
        for item in items
        if item["paper"].get("submittedOnDailyAt")
    ]
    if dates:
        newest_date = max(dates)
        items = [
            item for item in items
            if str(item["paper"].get("submittedOnDailyAt") or "")[:10]
            == newest_date
        ]
    items.sort(
        key=lambda item: (
            _safe_int(item["paper"].get("upvotes")),
            _safe_int(item.get("numComments")),
            bool(item["paper"].get("githubRepo")),
        ),
        reverse=True,
    )
    return items[: max(1, int(limit))]


def get_hf_daily():
    # Prefer the official API. Keep hf-mirror.com as a resilience fallback,
    # because connectivity differs across long-running deployment networks.
    proxy_url = os.getenv("HF_PROXY_URL", "").strip()
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    payload = None
    selected_url = ""
    errors = []
    for url in HF_DAILY_URLS:
        try:
            response = requests.get(
                url,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0 HumanGroupBot/1.0"},
                proxies=proxies,
            )
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, list) or not value:
                raise RuntimeError("empty or invalid Daily Papers response")
            payload = value
            selected_url = url
            break
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    if payload is None:
        print("HF Daily Papers 失败: " + " | ".join(errors), flush=True)
        return []

    papers = []
    for rank, item in enumerate(_rank_hf_daily_items(payload), start=1):
        paper = item.get("paper", {})
        arxiv_id = str(paper.get("id") or "").strip()
        if not re.fullmatch(r"\d{4}\.\d{4,5}", arxiv_id):
            continue
        github_repo = paper.get("githubRepo") or ""
        if isinstance(github_repo, dict):
            github_repo = github_repo.get("url") or github_repo.get("name") or ""
        papers.append(
            {
                "id": arxiv_id,
                "title": paper.get("title", ""),
                "summary": paper.get("summary", ""),
                "hf_upvotes": _safe_int(paper.get("upvotes")),
                "hf_comments": _safe_int(item.get("numComments")),
                "hf_organization": (
                    (item.get("organization") or {}).get("fullname")
                    or (paper.get("organization") or {}).get("fullname")
                    or ""
                ),
                "hf_project_url": str(paper.get("projectPage") or ""),
                "hf_github_url": str(github_repo or ""),
                "hf_thumbnail": str(item.get("thumbnail") or ""),
                "hf_daily_date": str(
                    paper.get("submittedOnDailyAt") or item.get("publishedAt") or ""
                )[:10],
                "hf_daily_rank": rank,
                "hf_daily_hot": True,
                "source": "Hugging Face Daily Papers",
            }
        )

    print(
        f"HF Daily Papers 热门获取成功: {len(papers)}（{selected_url}）",
        flush=True,
    )
    return papers


def _priority_verification_candidates(
    papers: list[dict],
    *,
    limit: int = 24,
    hf_reserve: int = 8,
) -> list[dict]:
    """Reserve daily verification capacity for HF community-hot papers."""
    hot = sorted(
        [paper for paper in papers if paper.get("hf_daily_hot")],
        key=lambda paper: (
            _safe_int(paper.get("hf_upvotes")),
            _safe_int(paper.get("hf_comments")),
        ),
        reverse=True,
    )[: max(0, min(int(hf_reserve), int(limit)))]
    selected = list(hot)
    identities = {_candidate_identity(paper) for paper in selected}
    for paper in papers:
        identity = _candidate_identity(paper)
        if not identity or identity in identities:
            continue
        identities.add(identity)
        selected.append(paper)
        if len(selected) >= int(limit):
            break
    return selected



def _rss_entry_to_paper(item):
    link = str(getattr(item, "link", ""))
    match = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", link)
    if not match:
        return None
    arxiv_id = match.group(1)
    title = re.sub(r"\s+", " ", str(getattr(item, "title", ""))).strip()
    abstract = re.sub(r"\s+", " ", str(getattr(item, "summary", ""))).strip()
    abstract = re.sub(
        rf"^arXiv:{re.escape(arxiv_id)}v\d+\s+Announce Type:\s*\w+\s+Abstract:\s*",
        "",
        abstract,
        flags=re.IGNORECASE,
    )
    creator = str(
        getattr(item, "author", "")
        or getattr(item, "dc_creator", "")
    ).strip()
    authors = [value.strip() for value in creator.split(",") if value.strip()]
    return {
        "id": arxiv_id,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "summary": abstract,
        "paper_url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
        "published": str(getattr(item, "published", "")),
        "updated": str(getattr(item, "updated", "")),
        "categories": [
            str(getattr(tag, "term", "") or tag.get("term", ""))
            for tag in getattr(item, "tags", [])
        ],
        "source": "arXiv RSS",
        "verified_source": True,
    }


def _paper_mentions_panorama(paper: dict) -> bool:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".casefold()
    return any(marker in text for marker in PANORAMA_MARKERS)


def get_arxiv_daily():
    """Read official arXiv RSS feeds, keeping panorama papers before truncation."""
    import feedparser

    proxy_url = os.getenv("ARXIV_PROXY_URL", "").strip()
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    papers = []
    errors = []
    for category in ("cs.CV", "cs.GR"):
        try:
            response = requests.get(
                f"https://rss.arxiv.org/rss/{category}",
                timeout=25,
                headers={"User-Agent": "Mozilla/5.0 HumanGroupBot/1.0"},
                proxies=proxies,
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            for item in feed.entries:
                paper = _rss_entry_to_paper(item)
                if paper:
                    papers.append(paper)
        except Exception as exc:
            errors.append(f"{category}: {exc}")

    unique = {}
    for paper in papers:
        unique.setdefault(paper["id"], paper)
    papers = list(unique.values())
    panorama = [paper for paper in papers if _paper_mentions_panorama(paper)]
    general = [paper for paper in papers if not _paper_mentions_panorama(paper)]
    selected = panorama[:5] + general[: max(0, 10 - len(panorama[:5]))]
    if selected:
        print(
            f"arXiv RSS 获取成功: {len(selected)}（全景相关 {len(panorama)}）",
            flush=True,
        )
        return selected
    print("arXiv RSS 失败: " + " | ".join(errors), flush=True)
    return []



def get_daily_papers():
    from source_health import track_source

    papers=[]

    for source_name, fetch in (
        ("official_reports", get_official_tech_reports),
        ("arxiv_rss", get_arxiv_daily),
    ):
        try:
            papers.extend(track_source(source_name, fetch, require_nonempty=True))
        except Exception as exc:
            print(f"{source_name} 来源不可用，继续使用候选池: {exc}", flush=True)

    try:
        hf_papers = track_source("huggingface_daily", get_hf_daily, require_nonempty=True)
    except Exception as exc:
        print(f"Hugging Face 来源不可用，继续使用候选池: {exc}", flush=True)
        hf_papers = []
    hf_by_id = {paper["id"]: paper for paper in hf_papers}
    if hf_by_id:
        verified_hf = _query_arxiv({"id_list": ",".join(hf_by_id)})
        for paper in verified_hf:
            signal = hf_by_id.get(paper.get("id", ""))
            if not signal:
                continue
            paper.update(
                {
                    key: value
                    for key, value in signal.items()
                    if key.startswith("hf_")
                }
            )
            paper["pdf_url"] = f"https://arxiv.org/pdf/{paper['id']}"
            paper["verified_source"] = True
            papers.append(paper)


    seen=set()
    result=[]

    for p in papers:
        identity = p.get("id") or p.get("title", "")
        if not identity:
            continue
        if identity in seen:
            existing = next(
                (item for item in result if (item.get("id") or item.get("title")) == identity),
                None,
            )
            if existing:
                existing.update({key: value for key, value in p.items() if key.startswith("hf_")})
            continue
        seen.add(identity)
        result.append(p)


    print(
        "最终候选:",
        len(result),
        flush=True
    )

    # Persisting happens before verification, so do not discard valid discoveries
    # here. The downstream verification batch still caps expensive work at 24.
    return result


def _panorama_requested(topics):
    return any(
        marker in str(topic).casefold()
        for topic in (topics or [])
        for marker in (
            "全景", "panorama", "panoramic", "360", "omnidirectional", "spherical",
        )
    )


def get_recent_arxiv_candidates(limit=40, topics=None):
    """Fetch recent verified papers when today's short list is exhausted."""
    try:
        major_papers = _query_arxiv(
            {
                "search_query": MAJOR_AI_QUERY,
                "start": 0,
                "max_results": min(24, limit),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
        general_papers = _query_arxiv(
            {
                "search_query": (
                    "cat:cs.CV OR cat:cs.AI OR cat:cs.LG OR cat:cs.RO OR "
                    "cat:cs.GR"
                ),
                "start": 0,
                "max_results": limit,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
        papers = []
        identities = set()
        for paper in major_papers + general_papers:
            identity = paper.get("id") or paper.get("title", "")
            if identity and identity not in identities:
                identities.add(identity)
                papers.append(paper)
        if _panorama_requested(topics):
            panorama_papers = _query_arxiv(
                {
                    "search_query": (
                        f"{PANORAMA_QUERY} AND "
                        "(cat:cs.CV OR cat:cs.GR)"
                    ),
                    "start": 0,
                    "max_results": min(40, limit),
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                }
            )
            identities = {paper.get("id") or paper.get("title", "") for paper in papers}
            for paper in panorama_papers:
                identity = paper.get("id") or paper.get("title", "")
                if identity and identity not in identities:
                    identities.add(identity)
                    papers.append(paper)
        recent = [paper for paper in papers if published_within_lookback(paper)]
        print(
            f"最近 {RECENT_LOOKBACK_DAYS} 天论文候选:",
            len(recent),
            flush=True,
        )
        return recent
    except Exception as exc:
        print(f"最近论文候选获取失败: {exc}", flush=True)
        return []


def get_tracked_recent_candidates(topics=None):
    """Treat the recent-arXiv query as an optional enrichment source."""
    from source_health import track_source

    last_error = None
    for attempt in range(2):
        try:
            return track_source(
                "arxiv_recent",
                lambda: get_recent_arxiv_candidates(topics=topics),
                require_nonempty=True,
            )
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                print(
                    "最近 arXiv 补充源被限流或暂时无结果，"
                    f"{ARXIV_RETRY_SECONDS // 60} 分钟后自动重试一次",
                    flush=True,
                )
                time.sleep(ARXIV_RETRY_SECONDS)
    print(
        f"最近 arXiv 补充源重试后仍不可用，"
        f"继续使用 RSS/HF/会议与候选池: {last_error}",
        flush=True,
    )
    return []


def _score_value(paper):
    try:
        return float(paper.get("score", 0))
    except (TypeError, ValueError):
        return 0.0


def _recommendation_priority(paper: dict) -> float:
    """Strongly prefer influential verified sources after the relevance gate."""
    tier = int(paper.get("institution_impact_tier") or 1)
    institution_bonus = {1: 0.0, 2: 0.65, 3: 1.1}.get(tier, 0.0)
    venue_bonus = 0.3 if (
        paper.get("conference_verified") or paper.get("journal_verified")
    ) else 0.0
    try:
        stars = max(0, int(paper.get("repo_stars") or 0))
    except (TypeError, ValueError):
        stars = 0
    repository_bonus = min(0.25, stars / 4000)
    return _score_value(paper) + institution_bonus + venue_bonus + repository_bonus


FOCUS_TOPIC_MARKERS = (
    "digital human", "virtual human", "avatar", "human motion", "motion generation",
    "motion synthesis", "embodied", "vision-language-action", "vla", "robot",
    "world model", "video generation", "video diffusion", "animation", "panorama",
    "panoramic", "360-degree", "omnidirectional", "spherical video",
    "multimodal", "multi-modal", "vision-language", "cross-modal", "omnimodal",
    "unified understanding and generation", "understanding and generation",
    "any-to-any", "interleaved generation",
    "visual agent", "vision agent", "agentic image", "agentic video",
    "image generation agent", "video agent", "image editing agent",
    "video editing agent", "3d agent", "agentic 3d", "3d scene agent",
)

KEYWORD_PATTERNS = (
    (("agentic", " agent", "multi-agent"), "Agent"),
    (("multimodal", "multi-modal", "cross-modal"), "Multimodal"),
    (("vision-language-action", " vla"), "VLA"),
    (("video generation", "text-to-video", "image-to-video"), "Video Generation"),
    (("image generation", "text-to-image", "image editing"), "Image Generation"),
    (("3d generation", "3d creation", "3d scene", "3d asset"), "3D Generation"),
    (("world model", "world modeling"), "World Model"),
    (("motion generation", "motion synthesis", "text-to-motion"), "Motion Generation"),
    (("digital human", "virtual human", "avatar"), "Digital Human"),
    (("diffusion", "flow matching"), "Diffusion / Flow"),
    (("gaussian splatting", "3dgs"), "3D Gaussian Splatting"),
    (("reinforcement learning", " rl "), "Reinforcement Learning"),
    (("large language model", " llm"), "LLM"),
    (("transformer",), "Transformer"),
)


def _paper_keywords(paper: dict, generated=None) -> list[str]:
    """Normalize 3–4 model keywords and deterministically fill omissions."""
    if isinstance(generated, str):
        raw_values = re.split(r"[,，、;；|]+", generated)
    elif isinstance(generated, list):
        raw_values = generated
    else:
        raw_values = []
    result = []
    for value in raw_values:
        keyword = re.sub(r"\s+", " ", str(value or "")).strip(" #`·,，;；")
        if keyword and len(keyword) <= 40 and keyword.casefold() not in {
            item.casefold() for item in result
        }:
            result.append(keyword)
        if len(result) >= 4:
            return result

    text = " ".join(
        [
            str(paper.get("title") or ""),
            str(paper.get("abstract") or paper.get("summary") or ""),
        ]
    ).casefold()
    padded_text = f" {text} "
    for markers, label in KEYWORD_PATTERNS:
        if any(marker in padded_text for marker in markers) and label.casefold() not in {
            item.casefold() for item in result
        }:
            result.append(label)
        if len(result) >= 4:
            break
    return result[:4]


def recommendation_track_for_time(push_time=None) -> str:
    """Use mornings for broad high-impact work and evenings for focus topics."""
    value = str(push_time or "").strip()
    try:
        hour = int(value.split(":", 1)[0])
    except (ValueError, IndexError):
        hour = datetime.now().hour
    return "major_impact" if hour < 12 else "focus_topics"


def _focus_topic_match(paper: dict) -> bool:
    if str(paper.get("track_fit") or "").casefold() in {"focus", "both", "focus_topics"}:
        return True
    text = " ".join(
        [
            str(paper.get("title") or ""),
            str(paper.get("abstract") or paper.get("summary") or ""),
            " ".join(str(value) for value in paper.get("categories", [])),
        ]
    ).casefold()
    return any(marker in text for marker in FOCUS_TOPIC_MARKERS)


def _track_priority(paper: dict, recommendation_track: str) -> tuple:
    base = _recommendation_priority(paper)
    tier = int(paper.get("institution_impact_tier") or 1)
    if recommendation_track == "major_impact":
        fit = str(paper.get("track_fit") or "").casefold() in {"major", "both", "major_impact"}
        return (int(fit), tier, base)
    return (int(_focus_topic_match(paper)), base, tier)


def select_with_complete_images(
    primary: list[dict],
    analyzed: list[dict],
    raw_papers: list[dict],
    limit: int,
    recommendation_track: str = "balanced",
) -> list[dict]:
    """Keep only papers with a complete teaser and a distinct method figure."""
    from paper_media import prepare_paper_images

    target_count = max(1, min(len(primary) or 1, limit))
    ordered = list(primary)
    ordered.extend(
        sorted(
            analyzed,
            key=lambda paper: _track_priority(paper, recommendation_track),
            reverse=True,
        )
    )
    ordered.extend(_verified_fallback(paper) for paper in raw_papers)
    selected = []
    seen = set()
    for paper in ordered:
        title = str(paper.get("title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        try:
            images = prepare_paper_images(paper)
        except Exception as exc:
            print(f"论文图片预检失败，跳过候选: {title}: {exc}", flush=True)
            continue
        kinds = {str(image.get("kind") or "") for image in images}
        if len(images) != 2 or kinds != {"teaser", "architecture"}:
            print(
                f"论文缺少完整 Teaser/架构图，跳过候选: {title}",
                flush=True,
            )
            continue
        selected.append(paper)
        if len(selected) >= target_count:
            break
    return selected


def _verified_fallback(paper):
    """Build a truthful card only from verified source metadata."""
    abstract = str(paper.get("abstract") or paper.get("summary") or "").strip()
    venue = str(paper.get("venue") or paper.get("source") or "官方论文页")
    return {
        "id": paper.get("id", ""),
        "title": paper.get("title", ""),
        "task": "自动分析暂不可用，请以摘要原文为准。",
        "main_method": "自动分析暂不可用，请以论文原文为准。",
        "summary": "本时段没有达到阈值的候选；这是最近未推送论文中的保底推荐。",
        "contributions": [],
        "score": 0,
        "reason": f"来自已核验的 {venue} 候选，保证每日推送至少一篇。",
        "opinion": "建议先阅读摘要与首页图，再决定是否精读。",
        "paper_url": paper.get("paper_url", ""),
        "pdf_url": paper.get("pdf_url", ""),
        "abstract": abstract,
        "authors": list(paper.get("authors", [])),
        "institutions": list(paper.get("institutions", [])),
        "institutions_source": paper.get("institutions_source", ""),
        "contributions_original": list(paper.get("contributions_original", [])),
        "contributions_original_source": paper.get(
            "contributions_original_source", ""
        ),
        "published": paper.get("published", ""),
        "updated": paper.get("updated", ""),
        "categories": list(paper.get("categories", [])),
        "source": paper.get("source", venue),
        "venue": venue,
        "code_url": paper.get("code_url", ""),
        "project_url": paper.get("project_url", ""),
        "metadata_verified": True,
        "conference_verified": bool(paper.get("conference_verified")),
        "official_venue_url": paper.get("official_venue_url", ""),
        "card_title": "📚 每日论文保底推荐",
        **{field: paper.get(field) for field in OPEN_SOURCE_FIELDS},
    }


def remove_duplicate(papers):

    library = load_library()

    old_titles = {
        p["title"]
        for p in library
    }


    return [
        p
        for p in papers
        if p["title"] not in old_titles
    ]



def analyze_paper(paper):

    prompt=f"""
你是顶会论文推荐专家。

分析论文：

标题:
{paper['title']}

摘要:
{paper['summary']}


严格返回JSON:

{{
"title":"",
"venue":"",
"summary":"",
"contributions":[],
"score":0,
"paper_url":"",
"code_url":""
}}
"""


    try:
        result = call_glm(prompt, timeout=180)
        data = parse_json_object(result)
    except Exception as exc:
        print(f"论文分析降级: {exc}", flush=True)
        data={
            "title":paper["title"],
            "summary":paper["summary"],
            "contributions":[],
            "score":0
        }


    data["paper_url"]=paper.get(
        "paper_url",
        ""
    )

    data["code_url"]=paper.get(
        "code_url",
        ""
    )

    return data


def analyze_papers_batch(papers, topics=None, recommendation_track="balanced"):
    """Analyze and rank all candidates in one model request."""
    if not papers:
        return []

    candidates = [
        {
            "title": paper.get("title", ""),
            "summary": paper.get("summary", ""),
            "paper_url": paper.get("paper_url", ""),
            "hf_upvotes": paper.get("hf_upvotes", 0),
            "hf_comments": paper.get("hf_comments", 0),
            "hf_organization": paper.get("hf_organization", ""),
            "institutions": list(paper.get("institutions", [])),
            "institution_impact_label": paper.get("institution_impact_label", ""),
            "team_evidence": paper.get("team_evidence", ""),
            "conference_verified": bool(paper.get("conference_verified")),
            "journal_verified": bool(paper.get("journal_verified")),
            "repo_stars": int(paper.get("repo_stars") or 0),
        }
        for paper in papers
    ]
    track_instruction = (
        "本轮是 08:00 大厂/高影响力场：优先大公司、顶级实验室、顶级高校和会影响行业技术路线的工作。"
        if recommendation_track == "major_impact"
        else "本轮是 20:00 垂直主题场：优先数字人、Motion Generation、具身智能/VLA、世界模型、视频生成、多模态及理解生成统一，以及图像/视频/3D 视觉 Agent。"
        if recommendation_track == "focus_topics"
        else "本轮采用影响力与主题相关性平衡排序。"
    )
    prompt = f"""
你是实验室顶会论文推荐专家。

实验室关注方向：
{json.dumps(topics or CONFIG["domains"], ensure_ascii=False)}

{track_instruction}

请一次性分析和评分下面的真实论文候选：
{json.dumps(candidates, ensure_ascii=False)}

严格返回一个 JSON 对象，不要使用 Markdown 代码块：
{{
  "papers": [
    {{
      "title": "必须与输入标题完全一致",
      "task": "一句话说明论文解决的研究任务，只能依据摘要",
      "main_method": "一到两句说明核心模型、模块或训练方法，只能依据摘要",
      "summary": "约220至300个中文字符的导读，依次说明研究问题、核心方法、关键结果和阅读价值，只能依据摘要",
      "keywords": ["3至4个核心技术关键词"],
      "one_line_insight": "40至70字的一句话结论，说明这篇论文最值得带走的技术认知",
      "contributions": ["摘要直接支持的贡献1", "摘要直接支持的贡献2"],
      "score": 0,
      "reason": "推荐理由",
      "opinion": "一句阅读建议，仅说明关注价值，不虚构局限",
	      "web_signal": "联网检索得到的官方发布或开源信号；没有则留空",
	      "track_fit": "major、focus、both 或 neither",
	      "keep": true
    }}
  ]
}}

score 使用 0 到 10，候选满足以下任一路径即可保留：
1. 大公司研究院/头部实验室发布、对通用 AI 有明显行业影响力的工作；
2. 与数字人、Motion Generation、具身智能、世界模型、视频、多模态、多模态理解生成统一，或图像/视频/3D 视觉 Agent 方向高度相关的工作。
第一类不因超出当前重点方向而被过滤；第二类仍需较强主题相关性。两类都要考虑创新性、技术深度、实验可信度和项目价值。
优先 OpenAI、Google/DeepMind、Meta、Microsoft、NVIDIA、Adobe、Apple、Amazon、字节、腾讯、阿里、百度等
大厂研究团队，以及顶级高校/研究机构、顶会正式录用、官方仓库活跃度高的论文。机构名气不能掩盖方法薄弱、
实验不充分或与主题无关，但在质量接近时应明确优先有影响力来源。
可以联网检索官方项目主页、官方代码、模型权重和机构发布，用作评分信号。
只允许根据输入标题、摘要、Hugging Face 热度和联网检索结果生成中文解读与评分。不得生成或修改作者、日期、
论文链接、PDF 链接、会议、期刊、项目主页或代码地址；不得编造实验结果。
关键词必须为 3 至 4 个精炼的技术概念，不要写成句子，不得超出标题与摘要的信息。
一句话结论必须直接概括论文核心认知，不写“本文提出”式空话，不得把未经摘要支持的判断写成结论。
"""

    try:
        result = call_glm(prompt, timeout=300, web_search=True)
        payload = parse_json_object(result)
    except Exception as exc:
        print(f"批量论文分析失败: {exc}", flush=True)
        return []

    originals = {paper.get("title", ""): paper for paper in papers}
    analyzed = []
    for item in payload.get("papers", []):
        if not isinstance(item, dict):
            continue
        original = originals.get(item.get("title", ""))
        if not original:
            continue
        item["paper_url"] = original.get("paper_url", "")
        item["keywords"] = _paper_keywords(original, item.get("keywords"))
        item["id"] = original.get("id", "")
        item["pdf_url"] = original.get("pdf_url", "")
        item["abstract"] = original.get("abstract", original.get("summary", ""))
        item["authors"] = list(original.get("authors", []))
        item["institutions"] = list(original.get("institutions", []))
        item["institutions_source"] = original.get("institutions_source", "")
        item["contributions_original"] = list(
            original.get("contributions_original", [])
        )
        item["contributions_original_source"] = original.get(
            "contributions_original_source", ""
        )
        item["published"] = original.get("published", "")
        item["updated"] = original.get("updated", "")
        item["categories"] = list(original.get("categories", []))
        item["source"] = original.get("source", "arXiv")
        item["venue"] = original.get("venue") or item["source"]
        item["code_url"] = original.get("code_url", "")
        item["project_url"] = original.get("project_url", "")
        for field in OPEN_SOURCE_FIELDS:
            item[field] = original.get(field)
        item["metadata_verified"] = True
        item["conference_verified"] = bool(original.get("conference_verified"))
        item["journal_verified"] = bool(original.get("journal_verified"))
        item["official_venue_url"] = original.get("official_venue_url", "")
        item["hf_upvotes"] = int(original.get("hf_upvotes") or 0)
        item["hf_comments"] = int(original.get("hf_comments") or 0)
        item["hf_organization"] = original.get("hf_organization", "")
        analyzed.append(item)

    return analyzed



def daily_push(
    chat_id=None,
    topics=None,
    max_papers=1,
    recommendation_track="balanced",
):

    init_db()


    print("抓取论文...",flush=True)


    from paper_candidate_pool import eligible_candidates, mark_candidates, store_candidates
    from source_health import track_source

    papers = [
        paper
        for paper in get_daily_papers()
        if published_within_lookback(paper)
    ]

    try:
        from alphaxiv_source import get_alphaxiv_candidates

        alphaxiv_papers = [
            paper
            for paper in track_source(
                "alphaxiv",
                lambda: get_alphaxiv_candidates(topics or CONFIG["domains"]),
                require_nonempty=True,
            )
            if published_within_lookback(paper)
        ]
        papers = alphaxiv_papers + [
            paper
            for paper in papers
            if (paper.get("id") or paper.get("title", ""))
            not in {item.get("id") or item.get("title", "") for item in alphaxiv_papers}
        ]
        print(f"alphaXiv 每日候选: {len(alphaxiv_papers)}", flush=True)
    except Exception as exc:
        print(f"alphaXiv 每日发现失败，继续使用其他来源: {exc}", flush=True)


    print(
        "候选数量:",
        len(papers),
        flush=True
    )


    target_chat_id = (chat_id or os.getenv("FEISHU_CHAT_ID") or "").strip()
    if not target_chat_id:
        raise RuntimeError("缺少飞书推送 chat_id")

    delivered_titles = get_delivered_titles(target_chat_id)
    try:
        from conference_papers import get_conference_candidates

        conference_papers = track_source(
            "conference_official",
            lambda: get_conference_candidates(
                topics,
                exclude_titles=delivered_titles,
                limit=4,
            ),
        )
    except Exception as exc:
        print(f"会议官方候选获取失败，继续使用 arXiv/HF: {exc}", flush=True)
        conference_papers = []
    try:
        from tpami_source import get_tpami_candidates

        tpami_papers = track_source(
            "tpami_2026",
            lambda: get_tpami_candidates(
                topics,
                exclude_titles=delivered_titles,
                limit=4,
            ),
        )
        if tpami_papers:
            print(
                "TPAMI 2026 官方候选: "
                + " | ".join(paper.get("title", "") for paper in tpami_papers),
                flush=True,
            )
    except Exception as exc:
        print(f"TPAMI 2026 候选获取失败，继续使用其他来源: {exc}", flush=True)
        tpami_papers = []
    try:
        from science_robotics_source import get_science_robotics_candidates

        science_robotics_papers = track_source(
            "science_robotics_2026",
            lambda: get_science_robotics_candidates(
                topics,
                exclude_titles=delivered_titles,
                limit=4,
            ),
        )
        if science_robotics_papers:
            print(
                "Science Robotics 2026 官方候选: "
                + " | ".join(
                    paper.get("title", "") for paper in science_robotics_papers
                ),
                flush=True,
            )
    except Exception as exc:
        print(f"Science Robotics 2026 候选获取失败，继续使用其他来源: {exc}", flush=True)
        science_robotics_papers = []
    try:
        from priority_journal_source import get_priority_journal_candidates

        priority_journal_papers = track_source(
            "priority_journals_2026",
            lambda: get_priority_journal_candidates(
                topics,
                exclude_titles=delivered_titles,
                limit=6,
            ),
        )
        if priority_journal_papers:
            print(
                "T-RO / RA-L / ACM TOG 2026 官方候选: "
                + " | ".join(
                    f"{paper.get('venue', '')}: {paper.get('title', '')}"
                    for paper in priority_journal_papers
                ),
                flush=True,
            )
    except Exception as exc:
        print(f"优先期刊候选获取失败，继续使用其他来源: {exc}", flush=True)
        priority_journal_papers = []
    papers = (
        priority_journal_papers
        + science_robotics_papers
        + tpami_papers
        + conference_papers
        + papers
    )

    papers=[
        p for p in papers
        if not paper_delivered(target_chat_id, p.get('title',''))
    ]

    # 每次都从最近 30 天补足较大的候选池，避免当天新论文尚未公开代码时无文可推；
    # 仍按 chat 去重，最终只会留下通过三层开源核验的论文。
    if len(papers) < 24:
        identities = {p.get("id") or p.get("title", "") for p in papers}
        for candidate in get_tracked_recent_candidates(topics=topics):
            identity = candidate.get("id") or candidate.get("title", "")
            if not identity or identity in identities:
                continue
            if paper_delivered(target_chat_id, candidate.get("title", "")):
                continue
            identities.add(identity)
            papers.append(candidate)
            if len(papers) >= 24:
                break


    store_candidates(papers)
    pooled = eligible_candidates(limit=60)
    identities = {p.get("id") or p.get("paper_url") or p.get("title", "") for p in papers}
    for candidate in pooled:
        identity = candidate.get("id") or candidate.get("paper_url") or candidate.get("title", "")
        if identity and identity not in identities:
            identities.add(identity)
            papers.append(candidate)

    papers = [
        paper for paper in papers
        if not paper_delivered(target_chat_id, paper.get("title", ""))
    ]

    print(
        "去重后:",
        len(papers),
        flush=True
    )

    # 开源代码是硬门槛。先由联网 LLM 确认论文与官方仓库的对应关系，
    # 再用 GitHub/GitLab API 和 README 做确定性复核；任何一层不通过都不推荐。
    from paper_opensource import filter_open_source_large_team

    verification_batch = _priority_verification_candidates(papers, limit=24)
    papers = filter_open_source_large_team(verification_batch)
    verified_identities = {
        paper.get("id") or paper.get("paper_url") or paper.get("title", "")
        for paper in papers
    }
    mark_candidates(papers, "verified")
    mark_candidates(
        [
            paper for paper in verification_batch
            if (paper.get("id") or paper.get("paper_url") or paper.get("title", ""))
            not in verified_identities
        ],
        "deferred",
        "open-source or team verification did not pass in this run",
    )
    print("三层核验后的开源大团队候选:", len(papers), flush=True)
    if not papers:
        print(
            "最新论文无合格候选，切换官方会议/期刊兜底池",
            flush=True,
        )
        expanded_official = _fetch_expanded_official_candidates(
            topics,
            delivered_titles,
        )
        store_candidates(expanded_official)
        attempted_identities = {
            _candidate_identity(paper) for paper in verification_batch
        }
        fallback_candidates = _official_venue_fallback_candidates(
            expanded_official,
            attempted_identities=attempted_identities,
            delivered_titles=delivered_titles,
        )
        papers, fallback_attempted = _verify_candidate_batches(
            fallback_candidates,
            filter_open_source_large_team,
            batch_size=16,
            target_count=max_papers,
        )
        fallback_verified_identities = {
            _candidate_identity(paper) for paper in papers
        }
        mark_candidates(papers, "verified")
        mark_candidates(
            [
                paper for paper in fallback_attempted
                if _candidate_identity(paper) not in fallback_verified_identities
            ],
            "deferred",
            "official fallback open-source or team verification did not pass",
        )
        print(
            "官方会议/期刊兜底核验后的开源大团队候选:",
            len(papers),
            flush=True,
        )
    if not papers:
        raise RuntimeError(
            "最新论文及官方会议/期刊列表均无同时通过 LLM、仓库 API 与 README 核验的未推送论文"
        )

    # 对已经通过开源核验的少量候选读取官方 PDF 首页机构，避免仅凭作者人数
    # 把普通团队误当成有影响力机构；随后把大公司、名校和顶级研究机构放到前面。
    from paper_metadata import enrich_papers_metadata
    from paper_opensource import institution_impact

    papers = enrich_papers_metadata(papers)
    for paper in papers:
        paper.update(institution_impact(paper))
    papers.sort(
        key=lambda paper: (
            int(paper.get("institution_impact_tier") or 1),
            bool(paper.get("conference_verified")),
            int(paper.get("repo_stars") or 0),
        ),
        reverse=True,
    )
    print(
        "影响力来源候选: "
        + " | ".join(
            f"{paper.get('title', '')}={paper.get('institution_impact_label', '大团队')}"
            for paper in papers[:10]
        ),
        flush=True,
    )

    analyzed = analyze_papers_batch(
        papers[:10],
        topics=topics,
        recommendation_track=recommendation_track,
    )
    selected = [
        paper
        for paper in analyzed
        if paper.get("keep")
        and _score_value(paper) >= CONFIG["min_score"]
    ]
    selected.sort(
        key=lambda paper: _track_priority(paper, recommendation_track),
        reverse=True,
    )

    print(
        "论文评分: "
        + " | ".join(
            f"{paper.get('title', '')}={paper.get('score', 0)}"
            for paper in sorted(
                analyzed,
                key=_score_value,
                reverse=True,
            )
        ),
        flush=True,
    )


    # 每日卡片保持精简：默认一篇，显式调用时最多两篇。
    max_papers = max(1, min(int(max_papers), 2))
    selected = selected[:max_papers]

    if not selected and analyzed:
        selected = [
            max(
                analyzed,
                key=lambda paper: _track_priority(paper, recommendation_track),
            )
        ]
        selected[0]["card_title"] = "📚 每日论文 · 本时段最佳"
        selected[0]["reason"] = (
            str(selected[0].get("reason") or "").strip()
            + f"（未达到 {CONFIG['min_score']}/10 阈值，作为本时段最高分候选推荐。）"
        ).strip()
        print("没有论文达到阈值，改推本时段最高分候选", flush=True)
    elif not selected and papers:
        selected = [_verified_fallback(papers[0])]
        print("模型分析不可用，改推已核验官方候选", flush=True)

    if not selected:
        raise RuntimeError("会议官网、arXiv 与 Hugging Face 均未返回可核验的未推送论文")

    selected = select_with_complete_images(
        selected,
        analyzed,
        papers,
        max_papers,
        recommendation_track=recommendation_track,
    )
    if not selected:
        raise RuntimeError(
            "候选论文均缺少可核验的完整 Teaser 或网络/方法架构图，本次未发送纯文字卡片"
        )

    selected = enrich_papers_metadata(selected)
    from paper_deep_reading import enrich_deep_readings

    selected = enrich_deep_readings(selected)
    from paper_bilingual import enrich_bilingual_papers

    selected = enrich_bilingual_papers(selected)

    for paper in selected:
        paper["push_time"] = datetime.now().strftime("%Y-%m-%d")

    try:
        from paper_archive import archive_papers

        document = archive_papers(selected, topics=topics)
        if document:
            for paper in selected:
                paper["feishu_doc_url"] = document["url"]
    except Exception as exc:
        print(f"论文库静默归档失败，将由后台重试: {exc}", flush=True)


    library=load_library()


    for paper in selected:


        send_feishu_message(
            target_chat_id,
            json.dumps(
                paper,
                ensure_ascii=False
            )
        )

        save_paper(paper)
        save_delivery(target_chat_id, paper.get("title", ""))
        # Delivery is chat-specific in paper_deliveries. Keep the shared candidate
        # verified so another subscribed chat can still receive it.
        mark_candidates([paper], "verified")

        library.append(
            paper
        )


    save_library(
        library
    )

    print(
        "今日推荐:",
        len(selected),
        flush=True
    )

    return len(selected)



if __name__=="__main__":
    daily_push()
