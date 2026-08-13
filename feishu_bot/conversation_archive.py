from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from daily_paper import parse_json_object
from glm_client import call_glm
from paper_archive import archive_papers
from paper_db import get_conn, init_db, save_paper
from paper_search import _query_arxiv


ARXIV_ID_PATTERN = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)
PAPER_WORDS = ("论文", "文献", "paper", "arxiv", "related work", "survey")


def _title_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _title_matches(candidate: str, verified: str) -> bool:
    left = _title_key(candidate)
    right = _title_key(verified)
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.9


def _extract_explicit_titles(text: str) -> list[str]:
    prompt = f"""
从下面对话中提取明确出现的学术论文英文标题。只提取对话原文中确实写出的标题；
不要根据主题推荐新论文，不要补全不确定的简称，不要提取新闻或网页标题。
严格返回 JSON 对象：{{"titles":["title 1"]}}。最多 6 个。

对话：
{text[:24000]}
"""
    try:
        payload = parse_json_object(call_glm(prompt, timeout=180, web_search=False))
    except Exception as exc:
        print(f"对话论文标题提取失败: {exc}", flush=True)
        return []
    return [
        str(title).strip()
        for title in payload.get("titles", [])[:6]
        if str(title).strip()
    ]


def _find_verified_papers(question: str, answer: str) -> list[dict]:
    combined = f"{question}\n{answer}"
    arxiv_ids = list(dict.fromkeys(ARXIV_ID_PATTERN.findall(combined)))
    verified = _query_arxiv({"id_list": ",".join(arxiv_ids)}) if arxiv_ids else []
    seen_ids = {paper.get("id") for paper in verified}

    lower = combined.casefold()
    if not any(word in lower for word in PAPER_WORDS):
        return verified

    for title in _extract_explicit_titles(combined):
        matches = _query_arxiv(
            {
                "search_query": f'ti:"{title}"',
                "start": 0,
                "max_results": 3,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
        )
        paper = next(
            (
                item
                for item in matches
                if _title_matches(title, str(item.get("title") or ""))
            ),
            None,
        )
        if paper and paper.get("id") not in seen_ids:
            verified.append(paper)
            seen_ids.add(paper.get("id"))
    return verified


def _already_archived(paper: dict) -> bool:
    init_db()
    conn = get_conn()
    arxiv_id = str(paper.get("id") or paper.get("arxiv_id") or "").strip()
    title = str(paper.get("title") or "").strip()
    if arxiv_id:
        row = conn.execute(
            """
            SELECT 1 FROM papers
            WHERE arxiv_id=? AND COALESCE(feishu_doc_url, '') != ''
            """,
            (arxiv_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT 1 FROM papers
            WHERE title=? AND COALESCE(feishu_doc_url, '') != ''
            """,
            (title,),
        ).fetchone()
    conn.close()
    return row is not None


def _enrich_for_archive(papers: list[dict]) -> list[dict]:
    incomplete = [
        paper
        for paper in papers
        if not paper.get("main_method") or not paper.get("contributions")
    ]
    if incomplete:
        source = [
            {
                "title": paper.get("title", ""),
                "abstract": paper.get("abstract") or paper.get("summary", ""),
            }
            for paper in incomplete
        ]
        prompt = f"""
你是严谨的论文资料整理员。只能依据输入的 arXiv 标题与摘要提炼信息，不得联网、不得猜测。
每篇必须返回 task、main_method、2 到 3 条 contributions 和一句 opinion。
严格返回 JSON 对象，不要 Markdown：
{{"papers":[{{"title":"与输入完全一致","task":"","main_method":"","contributions":["",""],"opinion":""}}]}}

输入：{json.dumps(source, ensure_ascii=False)}
"""
        try:
            payload = parse_json_object(
                call_glm(prompt, timeout=240, web_search=False)
            )
            enriched = {
                item.get("title"): item
                for item in payload.get("papers", [])
                if isinstance(item, dict)
            }
        except Exception as exc:
            print(f"对话论文结构化提炼失败，使用摘要降级: {exc}", flush=True)
            enriched = {}
    else:
        enriched = {}

    result = []
    for original in papers:
        paper = dict(original)
        item = enriched.get(paper.get("title"), {})
        paper["task"] = (
            paper.get("task") or item.get("task") or paper.get("summary")
            or paper.get("abstract") or "请查看摘要原文。"
        )
        paper["main_method"] = (
            paper.get("main_method") or paper.get("method")
            or item.get("main_method") or "请查看摘要中的方法描述。"
        )
        paper["contributions"] = (
            paper.get("contributions") or item.get("contributions")
            or ["请查看摘要原文中的贡献描述。"]
        )
        paper["opinion"] = (
            paper.get("opinion") or paper.get("insight") or item.get("opinion")
            or paper.get("reason") or "已核验并收录至论文库。"
        )
        paper["summary"] = paper.get("summary") or paper.get("abstract") or ""
        paper["venue"] = paper.get("venue") or "arXiv"
        paper["source"] = "arXiv"
        result.append(paper)
    from paper_metadata import enrich_papers_metadata
    from paper_bilingual import enrich_bilingual_papers

    return enrich_bilingual_papers(enrich_papers_metadata(result))


def archive_conversation_papers(papers: list[dict]) -> int:
    unique = []
    seen = set()
    for paper in papers:
        identity = paper.get("id") or paper.get("title")
        if not identity or identity in seen or _already_archived(paper):
            continue
        seen.add(identity)
        unique.append(paper)
    if not unique:
        return 0
    prepared = _enrich_for_archive(unique)
    # Persist first so the minute-level backfill job can retry if Feishu is down.
    for paper in prepared:
        save_paper(paper)
    archive_papers(prepared)
    return len(prepared)


def archive_papers_from_conversation(question: str, answer: str) -> int:
    papers = _find_verified_papers(question, answer)
    return archive_conversation_papers(papers)
