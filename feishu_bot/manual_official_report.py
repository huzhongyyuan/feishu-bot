from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

from daily_paper import analyze_papers_batch, get_official_tech_reports
from feishu_sender import send_message
from paper_archive import archive_papers
from paper_bilingual import enrich_bilingual_fields
from paper_db import init_db, save_delivery, save_paper
from paper_deep_reading import enrich_deep_reading
from paper_media import prepare_paper_images
from paper_metadata import enrich_papers_metadata
from paper_opensource import filter_open_source_large_team, institution_impact


def recommend_official_report(report_id: str, chat_id: str, topics: list[str]) -> dict:
    target_chat_id = (chat_id or os.getenv("FEISHU_CHAT_ID") or "").strip()
    if not target_chat_id:
        raise RuntimeError("缺少飞书推送 chat_id")

    reports = get_official_tech_reports()
    paper = next((item for item in reports if item.get("id") == report_id), None)
    if not paper:
        raise RuntimeError(f"官方报告未通过来源交叉核验：{report_id}")

    verified = filter_open_source_large_team([paper])
    if not verified:
        raise RuntimeError("官方报告、发布仓库与开源代码三层核验未通过")
    paper = enrich_papers_metadata(verified)[0]
    paper.update(institution_impact(paper))

    analyzed = analyze_papers_batch([paper], topics=topics)
    if not analyzed:
        raise RuntimeError("技术报告导读生成失败")
    paper = analyzed[0]
    paper["card_title"] = "论文推荐"

    images = prepare_paper_images(paper)
    if {item.get("kind") for item in images} != {"teaser", "architecture"}:
        raise RuntimeError("未能完整提取技术报告的 Teaser 与架构图")

    paper = enrich_deep_reading(paper)
    paper = enrich_bilingual_fields(paper)
    paper["push_time"] = datetime.now().strftime("%Y-%m-%d")
    document = archive_papers([paper], topics=topics)
    if document:
        paper["feishu_doc_url"] = document["url"]

    send_message(target_chat_id, json.dumps(paper, ensure_ascii=False))
    init_db()
    save_paper(paper)
    save_delivery(target_chat_id, paper.get("title", ""))
    return {
        "sent": True,
        "title": paper.get("title"),
        "score": paper.get("score"),
        "doc_url": paper.get("feishu_doc_url", ""),
        "images": [[item.get("kind"), item.get("figure_number")] for item in images],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="补发已交叉核验的官方 GitHub 技术报告")
    parser.add_argument("report_id")
    parser.add_argument("--chat-id", default="")
    parser.add_argument("--topic", action="append", dest="topics")
    args = parser.parse_args()
    result = recommend_official_report(
        args.report_id,
        args.chat_id,
        args.topics or ["大厂 AI", "Agent 基础设施"],
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
