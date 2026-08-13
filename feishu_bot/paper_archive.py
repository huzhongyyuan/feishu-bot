from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime

from feishu_docs import create_weekly_paper_document
from paper_db import get_conn, init_db, save_paper


DEFAULT_TOPICS = [
    "世界模型",
    "视频生成",
    "人体动作",
    "全景相机",
    "全景视频",
]


def _paper_year(paper: dict) -> int:
    for key in ("push_time", "week_start", "published", "week_end"):
        match = re.match(r"(20\d{2})", str(paper.get(key) or ""))
        if match:
            return int(match.group(1))
    return datetime.now().year


def _init_archive_documents() -> None:
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_archive_documents (
                year INTEGER PRIMARY KEY,
                document_id TEXT NOT NULL,
                url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def _get_year_document(year: int) -> dict | None:
    _init_archive_documents()
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM paper_archive_documents WHERE year=?",
            (year,),
        ).fetchone()
    return dict(row) if row else None


def _save_year_document(year: int, document: dict) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_archive_documents
            (year, document_id, url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(year) DO UPDATE SET
                document_id=excluded.document_id,
                url=excluded.url,
                updated_at=excluded.updated_at
            """,
            (year, document["document_id"], document["url"], now, now),
        )


def _archive_year(
    papers: list[dict],
    year: int,
    topics: list[str],
) -> dict | None:
    existing = _get_year_document(year)
    existing_url = str(existing.get("url") or "") if existing else ""

    pending: list[dict] = []
    with get_conn() as conn:
        for paper in papers:
            title = str(paper.get("title") or "").strip()
            if not title:
                continue
            row = conn.execute(
                "SELECT feishu_doc_url FROM papers WHERE title=?",
                (title,),
            ).fetchone()
            if existing_url and row and str(row[0] or "") == existing_url:
                continue
            pending.append(paper)

    if not pending:
        return existing

    date_values = [
        str(
            paper.get("push_time")
            or paper.get("week_start")
            or paper.get("published")
            or ""
        )[:10]
        for paper in pending
    ]
    date_values = [value for value in date_values if value]
    start_date = min(date_values) if date_values else f"{year}-01-01"
    end_date = max(date_values) if date_values else start_date
    document = create_weekly_paper_document(
        pending,
        start_date,
        end_date,
        topics,
        chat_id="",
        document_title=f"AI 论文总库｜{year}",
        existing_document_id=str(existing.get("document_id") or "")
        if existing
        else "",
    )
    _save_year_document(year, document)
    for paper in pending:
        paper["feishu_doc_url"] = document["url"]
        save_paper(paper)
    print(
        f"飞书 {year} 论文总库追加完成: {len(pending)} 篇, {document['url']}",
        flush=True,
    )
    return document


def _decode_json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        parsed = []
    return [str(item) for item in parsed if str(item).strip()]


def _decode_json(value: object, default: object) -> object:
    if isinstance(value, type(default)):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _decode_paper(row: dict) -> dict:
    paper = dict(row)
    arxiv_id = str(paper.get("arxiv_id") or "").strip()
    paper["id"] = arxiv_id
    paper["pdf_url"] = str(paper.get("pdf_url") or "").strip() or (
        f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else ""
    )
    paper["authors"] = _decode_json_list(paper.get("authors"))
    paper["institutions"] = _decode_json_list(paper.get("institutions"))
    paper["contributions_original"] = _decode_json_list(
        paper.get("contributions_original")
    )
    paper["categories"] = _decode_json_list(paper.get("categories"))
    paper["research_question"] = _decode_json(
        paper.get("research_question"), {}
    )
    for field in (
        "background",
        "method_result_map",
        "key_results",
        "evidence_chain",
        "discussion_highlights",
        "limitations",
        "writing_notes",
        "core_insights",
        "figure_insights",
        "reading_guide",
    ):
        paper[field] = _decode_json(paper.get(field), [])
    paper["contributions"] = [
        line.strip().lstrip("•- ").strip()
        for line in str(paper.get("contributions") or "").splitlines()
        if line.strip().lstrip("•- ").strip()
    ]
    return paper


def archive_papers(
    papers: list[dict],
    *,
    topics: list[str] | None = None,
) -> dict | None:
    """Append papers to one public read-only Feishu library per year."""
    if not papers:
        return None

    grouped: dict[int, list[dict]] = {}
    for paper in papers:
        grouped.setdefault(_paper_year(paper), []).append(paper)

    documents = [
        _archive_year(year_papers, year, topics or DEFAULT_TOPICS)
        for year, year_papers in sorted(grouped.items())
    ]
    return next((document for document in documents if document), None)


def archive_all_papers(year: int | None = None) -> int:
    """Migrate existing database rows into their yearly master documents."""
    init_db()
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM papers ORDER BY id ASC").fetchall()
    papers = [_decode_paper(dict(row)) for row in rows]
    if year is not None:
        papers = [paper for paper in papers if _paper_year(paper) == year]
    if papers:
        archive_papers(papers)
    return len(papers)


def archive_unstored_papers(limit: int = 8) -> int:
    """Backfill papers whose Feishu archive creation previously failed."""
    init_db()
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM papers
        WHERE COALESCE(feishu_doc_url, '') = ''
          AND COALESCE(title, '') != ''
        ORDER BY id ASC
        LIMIT ?
        """,
        (max(1, min(limit, 20)),),
    ).fetchall()
    conn.close()
    papers = [_decode_paper(dict(row)) for row in rows]
    if not papers:
        return 0
    archive_papers(papers)
    return len(papers)


if __name__ == "__main__":
    archive_unstored_papers()
