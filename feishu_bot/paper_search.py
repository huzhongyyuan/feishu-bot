from __future__ import annotations

import html
import re
import urllib.parse
from html.parser import HTMLParser

import feedparser
import requests


ARXIV_API = "https://export.arxiv.org/api/query"

# 常用论文简称直接映射到 arXiv ID，避免简称搜索歧义。
PAPER_ALIASES = {
    "infinitedance": "2603.13375",
    "infinite dance": "2603.13375",
    "uni3c": "2504.14899",
}


class _ArxivMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "meta":
            return
        values = {str(key).casefold(): str(value) for key, value in attrs}
        name = values.get("name", "")
        content = values.get("content", "")
        if name.startswith("citation_") and content:
            self.values.setdefault(name, []).append(html.unescape(content).strip())


def _display_author(value: str) -> str:
    parts = [part.strip() for part in str(value).split(",", 1)]
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 and all(parts) else str(value).strip()


def _fetch_arxiv_abs(arxiv_id: str) -> list[dict]:
    """Use the official abstract-page metadata when the Atom API is limited."""
    try:
        response = requests.get(
            f"https://arxiv.org/abs/{arxiv_id}",
            timeout=45,
            headers={"User-Agent": "HumanGroupBot/1.0 paper metadata fallback"},
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    parser = _ArxivMetaParser()
    parser.feed(response.text)
    values = parser.values
    title = " ".join(values.get("citation_title", [])[:1]).strip()
    abstract = " ".join(values.get("citation_abstract", [])[:1]).strip()
    if not title or not abstract:
        return []
    paper_url = f"https://arxiv.org/abs/{arxiv_id}"
    return [
        {
            "id": arxiv_id,
            "title": re.sub(r"\s+", " ", title),
            "authors": [_display_author(value) for value in values.get("citation_author", [])],
            "abstract": re.sub(r"\s+", " ", abstract),
            "summary": re.sub(r"\s+", " ", abstract),
            "url": paper_url,
            "paper_url": paper_url,
            "pdf_url": (values.get("citation_pdf_url") or [f"https://arxiv.org/pdf/{arxiv_id}"])[0],
            "published": (values.get("citation_date") or [""])[0],
            "updated": (values.get("citation_online_date") or [""])[0],
            "categories": [],
            "source": "arXiv",
            "verified_source": True,
            "metadata_source": "official_arxiv_abs",
        }
    ]


def _clean_query(text: str) -> str:
    """清理飞书 mention、中文指令词和多余标点。"""
    query = text.strip()

    query = re.sub(r"@_user_\d+", " ", query, flags=re.IGNORECASE)
    query = re.sub(r"@HumanGroupBot", " ", query, flags=re.IGNORECASE)

    command_words = [
        "请帮我",
        "帮我",
        "请",
        "介绍一下",
        "介绍",
        "分析一下",
        "分析",
        "讲一下",
        "总结一下",
        "总结",
        "这篇论文",
        "这篇paper",
        "论文",
        "paper",
    ]

    for word in command_words:
        query = re.sub(
            re.escape(word),
            " ",
            query,
            flags=re.IGNORECASE,
        )

    query = re.sub(r"[，。！？：；、,!?;:]+", " ", query)
    query = re.sub(r"\s+", " ", query).strip()

    return query


def _extract_arxiv_id(text: str) -> str | None:
    """支持 arXiv URL、带版本号 ID 和纯 ID。"""
    match = re.search(
        r"(?:arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5})(?:v\d+)?",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def _parse_entries(feed) -> list[dict]:
    papers = []

    for entry in getattr(feed, "entries", []):
        title = re.sub(r"\s+", " ", entry.title).strip()
        abstract = re.sub(r"\s+", " ", entry.summary).strip()

        arxiv_id = _extract_arxiv_id(entry.link) or ""
        paper_url = (
            f"https://arxiv.org/abs/{arxiv_id}"
            if arxiv_id
            else entry.link
        )

        papers.append(
            {
                "id": arxiv_id,
                "title": title,
                "authors": [
                    author.name
                    for author in getattr(entry, "authors", [])
                ],
                "abstract": abstract,
                # 保留 summary，兼容已有 paper_agent.py。
                "summary": abstract,
                "url": paper_url,
                "paper_url": paper_url,
                "pdf_url": (
                    f"https://arxiv.org/pdf/{arxiv_id}"
                    if arxiv_id
                    else ""
                ),
                "published": str(getattr(entry, "published", "")),
                "updated": str(getattr(entry, "updated", "")),
                "categories": [
                    tag.term for tag in getattr(entry, "tags", [])
                ],
                "source": "arXiv",
                "verified_source": True,
            }
        )

    return papers


def _query_arxiv(params: dict) -> list[dict]:
    query_string = urllib.parse.urlencode(params)
    feed = feedparser.parse(f"{ARXIV_API}?{query_string}")
    return _parse_entries(feed)


def search_arxiv(text: str, limit: int = 5) -> list[dict]:
    """
    检索优先级：
    1. arXiv URL/ID；
    2. 常用论文简称；
    3. 标题精确搜索；
    4. 全字段宽松搜索。
    """
    raw_text = text.strip()

    arxiv_id = _extract_arxiv_id(raw_text)
    if arxiv_id:
        papers = _query_arxiv({"id_list": arxiv_id})
        if papers:
            return papers
        papers = _fetch_arxiv_abs(arxiv_id)
        if papers:
            return papers

    query = _clean_query(raw_text)
    normalized = query.casefold()

    alias_id = PAPER_ALIASES.get(normalized)
    if alias_id:
        papers = _query_arxiv({"id_list": alias_id})
        if papers:
            return papers

    if not query:
        return []

    # 标题优先，避免 Uni3C 被误匹配为 Uni3D。
    papers = _query_arxiv(
        {
            "search_query": f'ti:"{query}"',
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )

    if papers:
        return papers

    # 标题搜索失败后，再做宽松全字段搜索。
    return _query_arxiv(
        {
            "search_query": f'all:"{query}"',
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
