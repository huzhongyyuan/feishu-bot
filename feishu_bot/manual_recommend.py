from __future__ import annotations

import argparse
import fcntl
import json
import os
from datetime import datetime
from pathlib import Path

import requests

from daily_paper import analyze_papers_batch
from feishu_sender import send_message
from paper_archive import archive_papers
from paper_bilingual import enrich_bilingual_fields
from paper_db import init_db, save_delivery, save_paper
from paper_deep_reading import enrich_deep_reading
from paper_media import prepare_paper_images
from paper_metadata import enrich_papers_metadata
from paper_opensource import (
    filter_open_source_large_team,
    institution_impact,
    verify_repository,
)
from paper_search import search_arxiv


def recommend_arxiv(
    arxiv_id: str,
    *,
    code_url: str,
    project_url: str = "",
    chat_id: str = "",
    license_pending: bool = False,
    topics: list[str] | None = None,
) -> dict:
    """Verify, enrich, archive and explicitly resend one requested paper."""
    target_chat_id = (chat_id or os.getenv("FEISHU_CHAT_ID") or "").strip()
    if not target_chat_id:
        raise RuntimeError("缺少飞书推送 chat_id")

    print("[1/7] 获取 arXiv 官方元数据", flush=True)
    papers = search_arxiv(arxiv_id, limit=1)
    if not papers or str(papers[0].get("id") or "") != arxiv_id:
        raise RuntimeError(f"arXiv 未返回指定论文：{arxiv_id}")
    paper = papers[0]
    paper.update({"code_url": code_url, "project_url": project_url})

    print("[2/7] 提取作者机构并核验官方仓库", flush=True)
    paper = enrich_papers_metadata([paper])[0]
    verified = filter_open_source_large_team([paper])
    if not verified:
        # Very recent papers may not yet appear in web-search indexes. For an
        # explicit manual request, accept the deterministic path only when the
        # official arXiv HTML itself links to the exact repository and the
        # repository API/README independently matches this paper.
        official_html = requests.get(
            f"https://arxiv.org/html/{arxiv_id}",
            timeout=45,
            headers={"User-Agent": "HumanGroupBot/1.0 official-code verifier"},
        )
        official_html.raise_for_status()
        normalized_code = code_url.rstrip("/").casefold()
        if normalized_code not in official_html.text.casefold():
            raise RuntimeError("arXiv 官方页未给出指定代码仓库")
        repository = verify_repository(code_url, paper)
        if not repository or len(paper.get("authors", [])) < 5:
            raise RuntimeError("官方仓库 API/README 或团队规模核验未通过")
        paper.update(repository)
        paper.update(institution_impact(paper))
        paper.update(
            {
                "open_source_verified": True,
                "large_team_verified": True,
                "team_evidence": f"作者团队 {len(paper.get('authors', []))} 人",
                "official_source_code_verified": True,
                "llm_open_source_verified": False,
                "llm_open_source_evidence": "arXiv 官方页 Code 链接与 GitHub API/README 双重核验",
            }
        )
    else:
        paper = verified[0]

    print("[3/7] 生成论文导读", flush=True)
    analyzed = analyze_papers_batch([paper], topics=topics)
    if not analyzed:
        raise RuntimeError("论文导读生成失败")
    paper = analyzed[0]
    paper["card_title"] = "论文推荐"
    if license_pending:
        paper["code_license_status"] = "pending"
        paper["llm_open_source_evidence"] = (
            str(paper.get("llm_open_source_evidence") or "").strip()
            + "；官方仓库已公开代码与资产入口，但最终许可证条款仍待补充。"
        ).strip("；")

    print("[4/7] 精确提取 Teaser 与网络架构图", flush=True)
    images = prepare_paper_images(paper)
    if {item.get("kind") for item in images} != {"teaser", "architecture"}:
        raise RuntimeError("未能完整提取 Teaser 与网络架构图")

    print("[5/7] 生成双语摘要与图文深度解析", flush=True)
    paper = enrich_deep_reading(paper)
    paper = enrich_bilingual_fields(paper)
    paper["push_time"] = datetime.now().strftime("%Y-%m-%d")

    print("[6/7] 写入年度飞书论文库", flush=True)
    document = archive_papers(paper and [paper], topics=topics)
    if document:
        paper["feishu_doc_url"] = document["url"]

    print("[7/7] 发送飞书卡片并在成功后记录", flush=True)
    send_message(target_chat_id, json.dumps(paper, ensure_ascii=False))
    init_db()
    save_paper(paper)
    save_delivery(target_chat_id, paper.get("title", ""))
    return {
        "sent": True,
        "title": paper.get("title"),
        "score": paper.get("score"),
        "doc_url": paper.get("feishu_doc_url", ""),
        "images": [
            [item.get("kind"), item.get("figure_number")] for item in images
        ],
        "code_license_status": paper.get("code_license_status", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="指定 arXiv 论文补发到飞书")
    parser.add_argument("arxiv_id")
    parser.add_argument("--code-url", required=True)
    parser.add_argument("--project-url", default="")
    parser.add_argument("--chat-id", default="")
    parser.add_argument("--license-pending", action="store_true")
    parser.add_argument("--topic", action="append", dest="topics")
    args = parser.parse_args()
    lock_path = Path(f"/tmp/humangroupbot-manual-{args.arxiv_id}.lock")
    with lock_path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"论文 {args.arxiv_id} 已有补发任务运行，拒绝重复启动"
            ) from exc
        result = recommend_arxiv(
            args.arxiv_id,
            code_url=args.code_url,
            project_url=args.project_url,
            chat_id=args.chat_id,
            license_pending=args.license_pending,
            topics=args.topics,
        )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
