from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
from difflib import SequenceMatcher
from types import SimpleNamespace
from pathlib import Path

import feedparser
import requests


DATA_DIR = Path(__file__).resolve().parent / "data"
LIST_CACHE = DATA_DIR / "conference_lists.json"
DETAIL_CACHE = DATA_DIR / "conference_details.json"
CACHE_SECONDS = 24 * 60 * 60
SIGGRAPH_VENUE = "SIGGRAPH 2026"
SIGGRAPH_SCHEDULE_SEARCH = "https://s2026.conference-schedule.org/search"
SIGGRAPH_LIST_CACHE = DATA_DIR / "siggraph_2026_schedule.json"

SOURCES = [
    {
        "venue": "CVPR 2026",
        "kind": "cvpr",
        "url": "https://openaccess.thecvf.com/CVPR2026?day=all",
    },
    {
        "venue": "ICML 2026",
        "kind": "icml",
        "url": "https://icml.cc/virtual/2026/papers.html?filter=titles",
    },
]

TOPIC_KEYWORDS = {
    "数字人": [
        "digital human", "virtual human", "human avatar", "neural avatar",
        "talking head", "audio-driven avatar", "facial animation",
    ],
    "Motion Generation": [
        "motion generation", "text-to-motion", "human motion generation",
        "motion synthesis", "motion editing", "gesture generation",
    ],
    "具身智能": [
        "embodied ai", "embodied intelligence", "vision-language-action",
        "vision language action", "vla", "robot learning", "robot manipulation",
        "humanoid robot", "robot policy",
    ],
    "世界模型": [
        "world model", "world modeling", "world modelling", "video prediction",
        "future prediction", "latent dynamics", "dynamics model",
    ],
    "视频生成": [
        "video generation", "text-to-video", "image-to-video", "video diffusion",
        "video synthesis", "video editing", "generative video",
    ],
    "人体动作": [
        "motion generation", "human motion", "motion synthesis", "motion capture",
        "human animation", "text-to-motion", "humanoid", "avatar", "human pose",
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


def _clean_html(value: object) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip().strip('"')


def _normalize_title(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _title_aliases(value: object) -> set[str]:
    """Normalize a title and its optional acronym-free form."""
    text = _clean_html(value)
    aliases = {_normalize_title(text)}
    if ":" in text:
        prefix, remainder = text.split(":", 1)
        if len(prefix.split()) <= 3:
            aliases.add(_normalize_title(remainder))
    return {alias for alias in aliases if alias}


def _request_text(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                timeout=60,
                headers={"User-Agent": "Mozilla/5.0 HumanGroupBot/1.0"},
            )
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"会议官方页面读取失败: {url}: {last_error}")


def parse_official_list(kind: str, text: str, base_url: str) -> list[dict]:
    if kind == "cvpr":
        matches = [
            (href, title)
            for href, title in re.findall(
                r'<dt class="ptitle">\s*<br>\s*<a href="([^"]+)"[^>]*>(.*?)</a>',
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
        ]
    elif kind == "eccv":
        matches = []
        pattern = re.compile(
            r'<dt class="ptitle">\s*<br>\s*<a href='
            r'(?:(?:"([^"]+)")|(?:\x27([^\x27]+)\x27)|([^\s>]+))[^>]*>(.*?)</a>',
            flags=re.IGNORECASE | re.DOTALL,
        )
        for quoted, single, bare, title in pattern.findall(text):
            href = quoted or single or bare
            if "eccv_2024" in href.casefold():
                matches.append((href, title))
    elif kind == "icml":
        matches = re.findall(
            r'<a[^>]+href="(/virtual/2026/poster/[^"]+)"[^>]*>(.*?)</a>',
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    else:
        raise ValueError(f"未知会议来源: {kind}")

    result = []
    seen = set()
    for href, raw_title in matches:
        title = _clean_html(raw_title)
        identity = _normalize_title(title)
        if not identity or identity in seen or title.casefold().startswith("position:"):
            continue
        seen.add(identity)
        result.append(
            {
                "title": title,
                "official_url": urllib.parse.urljoin(base_url, href),
            }
        )
    return result


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _official_lists() -> dict[str, list[dict]]:
    cached = _load_json(LIST_CACHE)
    fresh = time.time() - float(cached.get("updated_at") or 0) < CACHE_SECONDS
    if fresh and cached.get("sources"):
        return dict(cached["sources"])

    source_cache = dict(cached.get("sources") or {})
    for source in SOURCES:
        try:
            text = _request_text(source["url"])
            source_cache[source["venue"]] = parse_official_list(
                source["kind"], text, source["url"]
            )
        except Exception as exc:
            print(f"{source['venue']} 官方列表读取失败，使用缓存: {exc}", flush=True)
    if source_cache:
        _save_json(
            LIST_CACHE,
            {"updated_at": time.time(), "sources": source_cache},
        )
    return source_cache


def _meta_values(text: str, name: str) -> list[str]:
    return [
        html.unescape(value).strip()
        for value in re.findall(
            rf'<meta[^>]+name="{re.escape(name)}"[^>]+content="([^"]*)"',
            text,
            flags=re.IGNORECASE,
        )
    ]


def _div_text(text: str, element_id: str) -> str:
    match = re.search(
        rf'<div[^>]+id="{re.escape(element_id)}"[^>]*>(.*?)</div>',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _clean_html(match.group(1)) if match else ""


def _official_pdf_url(text: str, official_url: str) -> str:
    candidates = _meta_values(text, "citation_pdf_url")
    candidates.extend(
        re.findall(
            r'href=["\x27]([^"\x27]+(?:\.pdf(?:\?[^"\x27]*)?|/pdf\?id=[^"\x27]+))["\x27]',
            text,
            flags=re.IGNORECASE,
        )
    )
    for value in candidates:
        url = urllib.parse.urljoin(official_url, html.unescape(value))
        lowered = url.casefold()
        if "supp" not in lowered and url.startswith("https://"):
            return url
    return ""


def _title_match_score(left_title: str, right_title: str) -> float:
    return max(
        (
            SequenceMatcher(None, left, right).ratio()
            for left in _title_aliases(left_title)
            for right in _title_aliases(right_title)
        ),
        default=0.0,
    )


def _openalex_arxiv_entry(title: str):
    response = requests.get(
        "https://api.openalex.org/works",
        params={
            "filter": f"title.search:{title.split(':', 1)[-1].strip()}",
            "per-page": 10,
            "select": (
                "id,display_name,ids,best_oa_location,authorships,publication_date"
            ),
        },
        timeout=45,
        headers={"User-Agent": "HumanGroupBot/1.0"},
    )
    response.raise_for_status()
    best = None
    best_score = 0.0
    for work in response.json().get("results", []):
        score = _title_match_score(title, str(work.get("display_name") or ""))
        if score <= best_score:
            continue
        identifiers = work.get("ids") or {}
        location = work.get("best_oa_location") or {}
        identity_text = " ".join(
            str(value or "")
            for value in [
                identifiers.get("doi"),
                location.get("landing_page_url"),
                location.get("pdf_url"),
            ]
        )
        id_match = re.search(r"(?:arxiv[.:/]|abs/|pdf/)(\d{4}\.\d{4,5})", identity_text, re.I)
        if not id_match:
            continue
        best_score = score
        best = SimpleNamespace(
            id=f"https://arxiv.org/abs/{id_match.group(1)}",
            title=str(work.get("display_name") or title),
            published=str(work.get("publication_date") or ""),
            updated="",
            authors=[
                {"name": str((authorship.get("author") or {}).get("display_name") or "")}
                for authorship in work.get("authorships") or []
                if str((authorship.get("author") or {}).get("display_name") or "")
            ],
            tags=[],
        )
    return best if best_score >= 0.92 else None


def _arxiv_entry_for_title(title: str):
    aliases = _title_aliases(title)
    query_title = title.split(":", 1)[-1].strip() if ":" in title else title
    best = None
    best_score = 0.0
    try:
        response = requests.get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f'ti:"{query_title}"',
                "start": 0,
                "max_results": 8,
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
            timeout=60,
            headers={"User-Agent": "HumanGroupBot/1.0"},
        )
        response.raise_for_status()
        for entry in feedparser.parse(response.content).entries:
            entry_aliases = _title_aliases(getattr(entry, "title", ""))
            score = max(
                (
                    SequenceMatcher(None, left, right).ratio()
                    for left in aliases
                    for right in entry_aliases
                ),
                default=0.0,
            )
            if score > best_score:
                best = entry
                best_score = score
    except requests.RequestException as exc:
        print(f"arXiv API 暂不可用，改用 OpenAlex 核验: {exc}", flush=True)
    if best_score >= 0.92:
        return best
    return _openalex_arxiv_entry(title)


def enrich_conference_pdf(paper: dict) -> dict:
    """Attach a verified arXiv PDF when an official conference page omits it."""
    if str(paper.get("pdf_url") or "").startswith("https://"):
        return paper
    entry = _arxiv_entry_for_title(str(paper.get("title") or ""))
    if entry is None:
        return paper
    id_match = re.search(r"(\d{4}\.\d{4,5})", str(getattr(entry, "id", "")))
    if not id_match:
        return paper
    arxiv_id = id_match.group(1)
    enriched = dict(paper)
    enriched.update(
        {
            "id": arxiv_id,
            "paper_url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "published": str(getattr(entry, "published", "")) or paper.get("published", ""),
            "updated": str(getattr(entry, "updated", "")),
            "categories": [
                str(tag.get("term") or "")
                for tag in getattr(entry, "tags", [])
                if str(tag.get("term") or "")
            ],
            "source": f"{paper.get('venue') or '会议'} 官方录用论文 + arXiv",
        }
    )
    arxiv_authors = [
        str(author.get("name") or "").strip()
        for author in getattr(entry, "authors", [])
        if str(author.get("name") or "").strip()
    ]
    if arxiv_authors:
        enriched["authors"] = arxiv_authors
    return enriched


def _detail_paper(item: dict, venue: str) -> dict | None:
    official_url = item["official_url"]
    text = _request_text(official_url)
    title = item["title"]
    authors: list[str] = []
    abstract = ""
    pdf_url = ""
    published = ""

    if venue.startswith("CVPR"):
        title = (_meta_values(text, "citation_title") or [title])[0]
        authors = _meta_values(text, "citation_author")
        pdf_url = (_meta_values(text, "citation_pdf_url") or [""])[0]
        abstract = _div_text(text, "abstract")
    elif venue.startswith("ECCV"):
        title = _div_text(text, "papertitle") or title
        authors_text = _div_text(text, "authors")
        authors = [
            value.strip().rstrip("*")
            for value in re.split(r"[,;]", authors_text)
            if value.strip().rstrip("*")
        ]
        abstract = _div_text(text, "abstract")
        pdf_links = re.findall(
            r'href=["\x27]([^"\x27]+\.pdf)["\x27]',
            text,
            flags=re.IGNORECASE,
        )
        pdf_url = next(
            (
                urllib.parse.urljoin(official_url, value)
                for value in pdf_links
                if "supp" not in value.casefold()
            ),
            "",
        )
    elif venue.startswith("ICML"):
        for raw in re.findall(
            r'<script type="application/ld\+json">(.*?)</script>',
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            try:
                metadata = json.loads(raw)
            except json.JSONDecodeError:
                continue
            title = str(metadata.get("name") or title)
            authors = [
                str(author.get("name") or "").strip()
                for author in metadata.get("author", [])
                if str(author.get("name") or "").strip()
            ]
            published = str(metadata.get("datePublished") or "")
            break
        match = re.search(
            r'class="abstract-text-inner".*?<p[^>]*>(.*?)</p>',
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        abstract = _clean_html(match.group(1)) if match else ""
        pdf_url = _official_pdf_url(text, official_url)

    if not abstract or _normalize_title(title) != _normalize_title(item["title"]):
        return None
    paper = {
        "id": "",
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "summary": abstract,
        "paper_url": official_url,
        "pdf_url": pdf_url,
        "published": published,
        "updated": "",
        "categories": [],
        "source": f"{venue} 官方录用论文",
        "venue": venue,
        "verified_source": True,
        "metadata_verified": True,
        "conference_verified": True,
        "official_venue_url": next(
            source["url"] for source in SOURCES if source["venue"] == venue
        ),
    }
    if not paper["pdf_url"]:
        try:
            paper = enrich_conference_pdf(paper)
        except Exception as exc:
            print(f"{venue} arXiv PDF 补齐失败: {title}: {exc}", flush=True)
    return paper


def _keywords(topics: list[str] | None) -> list[str]:
    values = []
    for topic in topics or TOPIC_KEYWORDS:
        values.extend(TOPIC_KEYWORDS.get(topic, []))
        if re.search(r"[a-z]", str(topic), flags=re.IGNORECASE):
            values.append(str(topic).casefold())
    return list(dict.fromkeys(values or sum(TOPIC_KEYWORDS.values(), [])))


def _siggraph_official_schedule() -> dict[str, str]:
    cached = _load_json(SIGGRAPH_LIST_CACHE)
    if (
        time.time() - float(cached.get("updated_at") or 0) < CACHE_SECONDS
        and cached.get("papers")
    ):
        return dict(cached["papers"])

    response = requests.get(
        SIGGRAPH_SCHEDULE_SEARCH,
        # The official search page returns the full technical-paper index.
        params={"search": "MotionBricks"},
        timeout=60,
        headers={"User-Agent": "Mozilla/5.0 HumanGroupBot/1.0"},
    )
    response.raise_for_status()
    papers = {}
    for href, raw_title in re.findall(
        r'<a[^>]+href="([^"]*id=papers_\d+[^"]*)"[^>]*>(.*?)</a>',
        response.text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        title = _clean_html(raw_title)
        normalized = _normalize_title(title)
        if normalized and normalized not in papers:
            papers[normalized] = urllib.parse.urljoin(
                "https://s2026.conference-schedule.org/",
                html.unescape(href),
            )
    if papers:
        _save_json(
            SIGGRAPH_LIST_CACHE,
            {"updated_at": time.time(), "papers": papers},
        )
    return papers


def _siggraph_candidates(
    topics: list[str] | None,
    excluded: set[str],
    limit: int = 8,
) -> list[dict]:
    response = requests.get(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": 'all:"SIGGRAPH 2026"',
            "start": 0,
            "max_results": 80,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
        timeout=60,
        headers={"User-Agent": "HumanGroupBot/1.0"},
    )
    response.raise_for_status()
    keywords = _keywords(topics)
    official_schedule = _siggraph_official_schedule()
    ranked = []
    for entry in feedparser.parse(response.content).entries:
        title = _clean_html(getattr(entry, "title", ""))
        normalized = _normalize_title(title)
        comment = _clean_html(getattr(entry, "arxiv_comment", ""))
        comment_lower = comment.casefold()
        if not title or normalized in excluded or "siggraph 2026" not in comment_lower:
            continue
        if any(
            marker in comment_lower
            for marker in ("siggraph asia", "poster", "sca 2026", "planned to submit")
        ):
            continue
        abstract = _clean_html(getattr(entry, "summary", ""))
        searchable = f"{title} {abstract}".casefold()
        score = sum(
            max(1, len(keyword.split()))
            for keyword in keywords
            if keyword in searchable
        )
        if score:
            ranked.append((score, entry, title, abstract))
    ranked.sort(key=lambda item: -item[0])

    details = _load_json(DETAIL_CACHE)
    papers = []
    changed = False
    for _, entry, title, abstract in ranked[: max(limit + 2, 6)]:
        id_match = re.search(r"(\d{4}\.\d{4,5})", str(getattr(entry, "id", "")))
        if not id_match:
            continue
        arxiv_id = id_match.group(1)
        cache_key = f"{SIGGRAPH_VENUE}|{arxiv_id}"
        paper = details.get(cache_key)
        if not paper:
            official_url = official_schedule.get(_normalize_title(title), "")
            if not official_url:
                continue
            paper = {
                "id": arxiv_id,
                "title": title,
                "authors": [
                    str(author.get("name") or "").strip()
                    for author in getattr(entry, "authors", [])
                    if str(author.get("name") or "").strip()
                ],
                "abstract": abstract,
                "summary": abstract,
                "paper_url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "published": str(getattr(entry, "published", "")),
                "updated": str(getattr(entry, "updated", "")),
                "categories": [
                    str(tag.get("term") or "")
                    for tag in getattr(entry, "tags", [])
                    if str(tag.get("term") or "")
                ],
                "source": "SIGGRAPH 2026 官方日程 + arXiv",
                "venue": SIGGRAPH_VENUE,
                "verified_source": True,
                "metadata_verified": True,
                "conference_verified": True,
                "official_venue_url": official_url,
                "card_title": "SIGGRAPH 论文推荐",
            }
            details[cache_key] = paper
            changed = True
        papers.append(paper)
        if len(papers) >= limit:
            break
    if changed:
        _save_json(DETAIL_CACHE, details)
    return papers


def get_conference_candidates(
    topics: list[str] | None = None,
    *,
    exclude_titles: set[str] | None = None,
    limit: int = 4,
) -> list[dict]:
    official_lists = _official_lists()
    excluded = {_normalize_title(value) for value in (exclude_titles or set())}
    keywords = _keywords(topics)
    queues: dict[str, list[dict]] = {}
    for source in SOURCES:
        relevant = []
        for item in official_lists.get(source["venue"], []):
            normalized = _normalize_title(item["title"])
            if normalized in excluded:
                continue
            score = sum(
                max(1, len(keyword.split()))
                for keyword in keywords
                if keyword in item["title"].casefold()
            )
            if score:
                relevant.append((score, item))
        relevant.sort(key=lambda value: (-value[0], value[1]["title"].casefold()))
        queues[source["venue"]] = [item for _, item in relevant]

    try:
        queues[SIGGRAPH_VENUE] = _siggraph_candidates(
            topics,
            excluded,
            limit=max(4, limit),
        )
    except Exception as exc:
        print(f"SIGGRAPH 2026 候选读取失败，继续使用其他会议来源: {exc}", flush=True)
        queues[SIGGRAPH_VENUE] = []

    selected: list[tuple[str, dict]] = []
    venue_order = [source["venue"] for source in SOURCES] + [SIGGRAPH_VENUE]
    while len(selected) < max(1, min(limit, 8)):
        progressed = False
        for venue in venue_order:
            queue = queues.get(venue, [])
            if queue and len(selected) < limit:
                selected.append((venue, queue.pop(0)))
                progressed = True
        if not progressed:
            break

    details = _load_json(DETAIL_CACHE)
    papers = []
    changed = False
    for venue, item in selected:
        if venue == SIGGRAPH_VENUE:
            papers.append(item)
            continue
        cache_key = venue + "|" + item["official_url"]
        paper = details.get(cache_key)
        if not paper:
            try:
                paper = _detail_paper(item, venue)
            except Exception as exc:
                print(f"{venue} 论文详情读取失败: {item['title']}: {exc}", flush=True)
                continue
            if paper:
                details[cache_key] = paper
                changed = True
        elif not str(paper.get("pdf_url") or "").startswith("https://"):
            try:
                enriched = enrich_conference_pdf(paper)
            except Exception as exc:
                print(f"{venue} 缓存论文 PDF 补齐失败: {item['title']}: {exc}", flush=True)
            else:
                if enriched != paper:
                    paper = enriched
                    details[cache_key] = paper
                    changed = True
        if paper:
            papers.append(paper)
    if changed:
        _save_json(DETAIL_CACHE, details)
    print(
        "会议官方候选:",
        " | ".join(f"{paper['venue']}: {paper['title']}" for paper in papers),
        flush=True,
    )
    return papers
