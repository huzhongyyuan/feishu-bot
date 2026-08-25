"""High-priority 2026 robotics and graphics journal candidates."""

from __future__ import annotations

import re

import requests

from paper_search import _fetch_arxiv_abs, _query_arxiv
from tpami_source import _normalized_title, _published_date


SEMANTIC_BATCH = "https://api.semanticscholar.org/graph/v1/paper/batch"
JOURNALS = (
    {
        "venue": "IEEE T-RO 2026",
        "issn": "1552-3098",
        "container": "IEEE Transactions on Robotics",
        "doi_prefix": "10.1109/tro.",
    },
    {
        "venue": "IEEE RA-L 2026",
        "issn": "2377-3766",
        "container": "IEEE Robotics and Automation Letters",
        "doi_prefix": "10.1109/lra.",
    },
    {
        "venue": "ACM TOG 2026",
        "issn": "0730-0301",
        "container": "ACM Transactions on Graphics",
        "doi_prefix": "10.1145/",
    },
)
RELEVANCE_MARKERS = (
    "robot", "robotic", "humanoid", "embodied", "motion", "locomotion",
    "manipulation", "control", "planning", "navigation", "policy", "skill",
    "vision", "multimodal", "world model", "video", "human", "avatar",
    "animation", "generation", "generative", "3d", "scene", "shape",
    "geometry", "graphics", "rendering", "neural", "agent",
)


def _crossref_records(spec: dict, topics: list[str] | None) -> list[dict]:
    response = requests.get(
        f"https://api.crossref.org/journals/{spec['issn']}/works",
        params={
            "filter": "from-pub-date:2026-01-01,until-pub-date:2026-12-31,type:journal-article",
            "sort": "published",
            "order": "desc",
            "rows": 80,
            "select": "DOI,title,published,published-print,published-online,container-title,volume,issue,page",
        },
        timeout=45,
        headers={"User-Agent": "HumanGroupBot/1.0 priority journal monitor"},
    )
    response.raise_for_status()
    topic_words = {
        value
        for value in re.findall(
            r"[a-z0-9][a-z0-9-]{2,}", " ".join(topics or []).casefold()
        )
        if value not in {"agent", "generation"}
    }
    ranked = []
    for record in response.json().get("message", {}).get("items", []):
        title = str((record.get("title") or [""])[0]).strip()
        doi = str(record.get("DOI") or "").strip()
        containers = " ".join(record.get("container-title") or [])
        published = _published_date(record)
        title_text = title.casefold()
        score = sum(1 for marker in RELEVANCE_MARKERS if marker in title_text)
        score += sum(2 for word in topic_words if word in title_text)
        if (
            not title
            or not doi.casefold().startswith(spec["doi_prefix"])
            or spec["container"].casefold() not in containers.casefold()
            or not published.startswith("2026-")
            or score <= 0
        ):
            continue
        ranked.append((score, {**record, "_title": title, "_published": published}))
    ranked.sort(key=lambda item: -item[0])
    return [record for _, record in ranked[:30]]


def _semantic_arxiv_ids(records: list[dict]) -> dict[str, str]:
    if not records:
        return {}
    response = requests.post(
        SEMANTIC_BATCH,
        params={"fields": "title,externalIds"},
        json={"ids": [f"DOI:{record['DOI']}" for record in records]},
        timeout=45,
        headers={"User-Agent": "HumanGroupBot/1.0 priority journal monitor"},
    )
    response.raise_for_status()
    resolved = {}
    for record, item in zip(records, response.json()):
        if not isinstance(item, dict):
            continue
        arxiv_id = str((item.get("externalIds") or {}).get("ArXiv") or "").strip()
        if (
            re.fullmatch(r"\d{4}\.\d{4,5}", arxiv_id)
            and _normalized_title(item.get("title")) == _normalized_title(record["_title"])
        ):
            resolved[str(record["DOI"]).casefold()] = arxiv_id
    return resolved


def _official_arxiv(arxiv_ids: list[str]) -> dict[str, dict]:
    if not arxiv_ids:
        return {}
    papers = _query_arxiv({"id_list": ",".join(dict.fromkeys(arxiv_ids))})
    by_id = {str(paper.get("id") or ""): paper for paper in papers}
    for arxiv_id in arxiv_ids:
        if arxiv_id not in by_id:
            fallback = _fetch_arxiv_abs(arxiv_id)
            if fallback:
                by_id[arxiv_id] = fallback[0]
    return by_id


def get_priority_journal_candidates(
    topics: list[str] | None = None,
    *,
    exclude_titles: set[str] | None = None,
    limit: int = 6,
) -> list[dict]:
    """Return official journal records with exact, official arXiv matches."""
    excluded = {_normalized_title(value) for value in (exclude_titles or set())}
    records_by_venue = {
        spec["venue"]: _crossref_records(spec, topics) for spec in JOURNALS
    }
    all_records = [
        record for records in records_by_venue.values() for record in records
    ]
    resolved = _semantic_arxiv_ids(all_records)
    queues: dict[str, list[tuple[dict, str]]] = {}
    for spec in JOURNALS:
        queue = []
        for record in records_by_venue[spec["venue"]]:
            if _normalized_title(record["_title"]) in excluded:
                continue
            arxiv_id = resolved.get(str(record.get("DOI") or "").casefold(), "")
            if arxiv_id:
                queue.append((record, arxiv_id))
            if len(queue) >= 4:
                break
        queues[spec["venue"]] = queue

    selected: list[tuple[dict, dict, str]] = []
    target = max(1, min(int(limit), 10))
    while len(selected) < target * 2:
        progressed = False
        for spec in JOURNALS:
            queue = queues[spec["venue"]]
            if queue:
                record, arxiv_id = queue.pop(0)
                selected.append((spec, record, arxiv_id))
                progressed = True
        if not progressed:
            break

    official = _official_arxiv([arxiv_id for _, _, arxiv_id in selected])
    result = []
    for spec, record, arxiv_id in selected:
        paper = official.get(arxiv_id)
        if not paper or _normalized_title(paper.get("title")) != _normalized_title(record["_title"]):
            continue
        doi = str(record["DOI"]).strip()
        enriched = dict(paper)
        enriched.update(
            {
                "venue": spec["venue"],
                "source": f"{spec['venue']} · Crossref/Semantic Scholar/arXiv verified",
                "journal_verified": True,
                "metadata_verified": True,
                "official_venue_url": f"https://doi.org/{doi}",
                "journal_published": record["_published"],
                "journal_volume": str(record.get("volume") or ""),
                "journal_issue": str(record.get("issue") or ""),
                "journal_pages": str(record.get("page") or ""),
            }
        )
        result.append(enriched)
        if len(result) >= target:
            break
    return result
