"""Verified IEEE TPAMI 2026 candidates backed by Crossref and arXiv."""

from __future__ import annotations

import re
from datetime import datetime

import requests

from paper_search import _query_arxiv


CROSSREF_WORKS = "https://api.crossref.org/journals/0162-8828/works"
TPAMI_NAME = "IEEE Transactions on Pattern Analysis and Machine Intelligence"
GENERAL_VISION_MARKERS = (
    "image", "video", "vision", "visual", "3d", "multimodal", "motion",
    "generation", "learning", "transformer", "attention", "agent", "robot",
    "world model", "avatar", "human", "segmentation", "detection", "tracking",
)


def _normalized_title(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _published_date(item: dict) -> str:
    for field in ("published-print", "published-online", "published", "issued"):
        parts = ((item.get(field) or {}).get("date-parts") or [[]])[0]
        if parts:
            values = [int(value) for value in parts[:3]]
            values += [1] * (3 - len(values))
            try:
                return datetime(*values).date().isoformat()
            except ValueError:
                continue
    return ""


def get_tpami_candidates(
    topics: list[str] | None = None,
    *,
    exclude_titles: set[str] | None = None,
    limit: int = 4,
) -> list[dict]:
    """Return exact arXiv matches for relevant official TPAMI 2026 records."""
    response = requests.get(
        CROSSREF_WORKS,
        params={
            "filter": "from-pub-date:2026-01-01,until-pub-date:2026-12-31,type:journal-article",
            "sort": "published",
            "order": "desc",
            "rows": 60,
            "select": "DOI,title,author,published,published-print,published-online,URL,container-title,volume,issue,page",
        },
        timeout=45,
        headers={"User-Agent": "HumanGroupBot/1.0 TPAMI monitor"},
    )
    response.raise_for_status()
    records = response.json().get("message", {}).get("items", [])
    excluded = {_normalized_title(value) for value in (exclude_titles or set())}
    topic_text = " ".join(topics or []).casefold()
    topic_words = {
        value
        for value in re.findall(r"[a-z0-9][a-z0-9-]{2,}", topic_text)
        if value not in {"agent", "generation"}
    }
    result = []
    for record in records:
        titles = record.get("title") or []
        title = str(titles[0] if titles else "").strip()
        normalized = _normalized_title(title)
        doi = str(record.get("DOI") or "").strip()
        containers = " ".join(record.get("container-title") or [])
        published = _published_date(record)
        title_text = title.casefold()
        relevant = any(marker in title_text for marker in GENERAL_VISION_MARKERS) or any(
            word in title_text for word in topic_words
        )
        if (
            not title
            or normalized in excluded
            or not doi.casefold().startswith("10.1109/tpami.")
            or TPAMI_NAME.casefold() not in containers.casefold()
            or not published.startswith("2026-")
            or not relevant
        ):
            continue
        matches = _query_arxiv(
            {
                "search_query": f'ti:"{title}"',
                "start": 0,
                "max_results": 5,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
        )
        paper = next(
            (item for item in matches if _normalized_title(item.get("title")) == normalized),
            None,
        )
        if not paper:
            continue
        paper = dict(paper)
        paper.update(
            {
                "venue": "IEEE TPAMI 2026",
                "source": "IEEE TPAMI 2026 · Crossref/arXiv verified",
                "journal_verified": True,
                "metadata_verified": True,
                "official_venue_url": f"https://doi.org/{doi}",
                "journal_published": published,
                "journal_volume": str(record.get("volume") or ""),
                "journal_issue": str(record.get("issue") or ""),
                "journal_pages": str(record.get("page") or ""),
            }
        )
        result.append(paper)
        if len(result) >= max(1, min(int(limit), 10)):
            break
    return result
