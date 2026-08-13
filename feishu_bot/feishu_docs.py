from __future__ import annotations

import json
import os
import time
import urllib.parse
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

from feishu_sender import get_token
from feishu_text import format_latex_for_feishu


load_dotenv()
BASE_URL = "https://open.feishu.cn/open-apis"


def _request(method: str, path: str, token: str, **kwargs) -> dict:
    response = requests.request(
        method,
        f"{BASE_URL}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        timeout=60,
        **kwargs,
    )
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(f"飞书文档接口返回非 JSON：HTTP {response.status_code}") from exc
    if response.status_code >= 400 or result.get("code", 0) != 0:
        raise RuntimeError(f"飞书文档接口失败：HTTP {response.status_code}，{result}")
    return result


def _text_run(content: str, *, bold: bool = False, link: str = "") -> dict:
    style = {"bold": bold}
    if link:
        style["link"] = {"url": urllib.parse.quote(link, safe="")}
    return {
        "text_run": {
            "content": content,
            "text_element_style": style,
        }
    }


def _text_block(elements: list[dict]) -> dict:
    return {
        "block_type": 2,
        "text": {
            "elements": elements,
            "style": {},
        },
    }


def _heading_block(content: str, level: int = 2) -> dict:
    level = max(1, min(9, level))
    return {
        "block_type": level + 2,
        f"heading{level}": {
            "elements": [_text_run(content)],
            "style": {},
        },
    }


def _list_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [
            format_latex_for_feishu(item)
            for item in value
            if str(item).strip()
        ]
    return [
        format_latex_for_feishu(line.strip().lstrip("•- ").strip())
        for line in str(value or "").splitlines()
        if line.strip().lstrip("•- ").strip()
    ]


def _sourced_lines(value: object, *, limit: int = 5) -> list[str]:
    values = value if isinstance(value, list) else []
    result = []
    for item in values:
        if isinstance(item, dict):
            text = format_latex_for_feishu(item.get("text"))
            source = str(item.get("source") or "原文未明确").strip()
        else:
            text = format_latex_for_feishu(item)
            source = "原文未明确"
        if not text:
            continue
        label = source if "编辑解读" in source else (
            "原文未明确" if source == "原文未明确" else f"原文事实 · {source}"
        )
        result.append(f"• {text}\n  [{label}]")
        if len(result) >= limit:
            break
    return result


def _method_result_lines(value: object, *, limit: int = 5) -> list[str]:
    values = value if isinstance(value, list) else []
    result = []
    for item in values:
        if not isinstance(item, dict):
            continue
        method = format_latex_for_feishu(item.get("method"))
        evidence = format_latex_for_feishu(item.get("result"))
        source = str(item.get("source") or "原文未明确")
        if not method:
            continue
        result.append(
            f"• {method} → {evidence or '原文未明确对应结果'}\n"
            f"  [{'原文未明确' if source == '原文未明确' else '原文事实 · ' + source}]"
        )
        if len(result) >= limit:
            break
    return result


def _core_insight_lines(value: object, *, limit: int = 3) -> list[str]:
    values = value if isinstance(value, list) else []
    result = []
    for index, item in enumerate(values, start=1):
        if not isinstance(item, dict):
            continue
        finding = format_latex_for_feishu(item.get("finding"))
        why = format_latex_for_feishu(item.get("why_it_matters"))
        transfer = format_latex_for_feishu(item.get("transfer"))
        source = str(item.get("source") or "原文未明确").strip()
        if not finding:
            continue
        lines = [f"Insight {index}｜{finding}"]
        if why:
            lines.append(f"为什么重要（编辑解读）：{why}")
        if transfer:
            lines.append(f"可迁移启示（编辑解读）：{transfer}")
        lines.append(
            f"[{'原文未明确' if source == '原文未明确' else '原文事实 · ' + source}]"
        )
        result.append("\n".join(lines))
        if len(result) >= limit:
            break
    return result


def _figure_insight_for(paper: dict, figure_number: int) -> dict:
    for item in paper.get("figure_insights") or []:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("figure_number") or 0)
        except (TypeError, ValueError):
            continue
        if number == figure_number:
            return item
    return {}


def _summary_table_payload(papers: list[dict], *, index: int = 3) -> dict:
    rows = [["论文信息", "研究任务", "核心图", "主要方法", "主要贡献", "评分 / 观点"]]
    for paper in papers:
        contributions = _list_values(paper.get("contributions"))
        original_contributions = _list_values(
            paper.get("contributions_original")
        )
        contribution_text = "\n".join(f"• {value}" for value in contributions)
        if not contribution_text:
            contribution_text = "以论文摘要原文为准，暂无可核验的贡献提炼。"
        if original_contributions:
            contribution_text += "\n\nContributions · 英文原文\n" + "\n".join(
                f"{index}. {value}"
                for index, value in enumerate(original_contributions, start=1)
            )
        question = paper.get("research_question") or {}
        question_text = (
            question.get("text") if isinstance(question, dict) else question
        )
        rows.append(
            [
                format_latex_for_feishu(paper.get("title")),
                format_latex_for_feishu(
                    question_text or paper.get("task") or paper.get("summary")
                ),
                "",
                format_latex_for_feishu(
                    paper.get("main_method") or "以论文摘要中的方法描述为准。"
                ),
                contribution_text,
                (
                    f"⭐ {paper.get('score', '-')}/10\n"
                    f"{format_latex_for_feishu(paper.get('opinion') or paper.get('reason'))}"
                ),
            ]
        )

    table_id = f"table_{uuid.uuid4().hex}"
    cell_ids = []
    descendants = []
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            cell_id = f"cell_{uuid.uuid4().hex}"
            text_id = f"text_{uuid.uuid4().hex}"
            cell_ids.append(cell_id)
            descendants.append(
                {
                    "block_id": cell_id,
                    "block_type": 32,
                    "table_cell": {},
                    "children": [text_id],
                }
            )
            paper = papers[row_index - 1] if row_index > 0 else None
            if paper and column_index == 0:
                authors = [
                    str(item).strip()
                    for item in paper.get("authors", [])
                    if str(item).strip()
                ]
                institutions = [
                    str(item).strip()
                    for item in paper.get("institutions", [])
                    if str(item).strip()
                ]
                author_text = "、".join(authors[:6]) + (
                    " 等" if len(authors) > 6 else ""
                )
                institution_text = "、".join(institutions[:4]) + (
                    " 等" if len(institutions) > 4 else ""
                )
                date_text = str(
                    paper.get("push_time")
                    or paper.get("published")
                    or paper.get("week_start")
                    or ""
                )[:10]
                venue_text = format_latex_for_feishu(
                    paper.get("venue") or paper.get("source") or "官方论文来源"
                )
                code_url = str(paper.get("code_url") or "").strip()
                code_label = (
                    "官方公开代码（许可证待补充）"
                    if str(paper.get("code_license_status") or "").casefold() == "pending"
                    else "开源代码（已核验）"
                )
                elements = [
                    _text_run(str(value), bold=True),
                    _text_run(
                        f"\n日期：{date_text or '未提供'}　来源：{venue_text}"
                    ),
                    _text_run(f"\n作者：{author_text or '官方元数据未提供'}"),
                    _text_run(
                        "\n机构："
                        + (institution_text or "官方 PDF 首页未明确提供")
                    ),
                    _text_run(
                        "\n阅读论文官方页",
                        link=str(paper.get("paper_url") or ""),
                    ),
                ]
                if code_url:
                    elements.append(
                        _text_run(
                            f"　｜　{code_label}",
                            bold=True,
                            link=code_url,
                        )
                    )
            else:
                elements = [_text_run(str(value), bold=row_index == 0)]
            descendants.append(
                {
                    "block_id": text_id,
                    "block_type": 2,
                    "text": {
                        "elements": elements,
                        "style": {},
                    },
                    "children": [],
                }
            )

    descendants.insert(
        0,
        {
            "block_id": table_id,
            "block_type": 31,
            "table": {
                "property": {
                    "row_size": len(rows),
                    "column_size": 6,
                    "column_width": [235, 190, 285, 220, 245, 185],
                }
            },
            "children": cell_ids,
        },
    )
    return {
        "children_id": [table_id],
        "descendants": descendants,
        "index": max(0, int(index)),
    }


def _get_document_blocks(document_id: str, token: str) -> list[dict]:
    blocks: list[dict] = []
    page_token = ""
    while True:
        query = "page_size=500"
        if page_token:
            query += "&page_token=" + urllib.parse.quote(page_token, safe="")
        result = _request(
            "GET",
            f"/docx/v1/documents/{document_id}/blocks?{query}",
            token,
        )
        data = result.get("data", {})
        blocks.extend(data.get("items", []))
        if not data.get("has_more"):
            return blocks
        page_token = str(data.get("page_token") or "")
        if not page_token:
            return blocks


def _root_child_count(document_id: str, token: str) -> int:
    blocks = _get_document_blocks(document_id, token)
    root = next(
        (block for block in blocks if block.get("block_id") == document_id),
        blocks[0] if blocks else {},
    )
    return len(root.get("children", []))


def _fill_table_images(
    token: str,
    document_id: str,
    paper_images: list[list[dict]],
    table_id: str = "",
) -> None:
    blocks = _get_document_blocks(document_id, token)
    tables = [block for block in blocks if block.get("block_type") == 31]
    if not tables:
        raise RuntimeError("飞书文档对比表创建后未找到表格块")
    table = next(
        (block for block in tables if block.get("block_id") == table_id),
        tables[-1],
    )
    cell_ids = list(table.get("children", []))
    expected_cells = (len(paper_images) + 1) * 6
    if len(cell_ids) < expected_cells:
        raise RuntimeError(
            f"飞书文档表格单元格数量异常：{len(cell_ids)} < {expected_cells}"
        )

    for paper_index, images in enumerate(paper_images):
        if not images:
            continue
        # Table cells are returned row-major. Column 2 is the image column.
        image_cell_id = cell_ids[(paper_index + 1) * 6 + 2]
        time.sleep(0.4)
        created = _request(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{image_cell_id}/children",
            token,
            json={
                "children": [
                    {
                        "block_type": 27,
                        "image": {
                            "width": 300,
                            "height": 180,
                            "align": 2,
                            "caption": {"content": "Figure 1 + Caption"},
                        },
                    }
                ]
            },
        )
        image_block = next(
            (
                child
                for child in created.get("data", {}).get("children", [])
                if child.get("block_type") == 27
            ),
            None,
        )
        if image_block:
            _upload_docx_image(
                token,
                document_id,
                image_block["block_id"],
                images[0]["path"],
            )


def _upload_docx_image(
    token: str,
    document_id: str,
    image_block_id: str,
    image_path: str | Path,
) -> None:
    path = Path(image_path)
    with path.open("rb") as image_file:
        response = requests.post(
            f"{BASE_URL}/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": path.name,
                "parent_type": "docx_image",
                "parent_node": image_block_id,
                "size": str(path.stat().st_size),
                "extra": json.dumps({"drive_route_token": document_id}),
            },
            files={"file": (path.name, image_file, "image/jpeg")},
            timeout=90,
        )
    result = response.json()
    if response.status_code >= 400 or result.get("code", 0) != 0:
        raise RuntimeError(f"飞书文档图片上传失败：{result}")
    file_token = result["data"]["file_token"]
    _request(
        "PATCH",
        f"/docx/v1/documents/{document_id}/blocks/{image_block_id}",
        token,
        json={"replace_image": {"token": file_token}},
    )


def _append_deep_images(
    token: str,
    document_id: str,
    paper: dict,
    images: list[dict],
) -> None:
    """Append complete PDF figures with captions and evidence-aware insights."""
    for index, image in enumerate(images, start=1):
        figure_number = int(image.get("figure_number") or 0)
        page_number = int(image.get("page_number") or 0)
        label = str(image.get("label") or f"Figure {figure_number}")
        _request(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            token,
            json={"children": [_heading_block(f"图 {index}｜{label}", level=3)]},
        )
        created = _request(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            token,
            json={
                "children": [
                    {
                        "block_type": 27,
                        "image": {
                            "width": int(image.get("width") or 720),
                            "height": int(image.get("height") or 420),
                            "align": 2,
                            "caption": {"content": label},
                        },
                    }
                ]
            },
        )
        image_block = next(
            (
                child
                for child in created.get("data", {}).get("children", [])
                if child.get("block_type") == 27
            ),
            None,
        )
        if not image_block:
            raise RuntimeError(f"飞书文档图片块创建失败：{label}")
        _upload_docx_image(
            token,
            document_id,
            image_block["block_id"],
            image["path"],
        )

        insight = _figure_insight_for(paper, figure_number)
        caption = format_latex_for_feishu(image.get("caption"))
        lines = [
            f"原文 Caption：{caption}",
            f"[原文事实 · PDF p.{page_number} / Figure {figure_number}]",
        ]
        what_it_shows = format_latex_for_feishu(insight.get("what_it_shows"))
        why_it_matters = format_latex_for_feishu(insight.get("why_it_matters"))
        reading_tip = format_latex_for_feishu(insight.get("reading_tip"))
        if what_it_shows:
            lines.append(f"这张图展示了什么：{what_it_shows}")
        if why_it_matters:
            lines.append(f"为什么重要（编辑解读）：{why_it_matters}")
        if reading_tip:
            lines.append(f"读图重点（编辑解读）：{reading_tip}")
        _request(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            token,
            json={"children": [_text_block([_text_run("\n".join(lines))])]},
        )
        time.sleep(0.3)


def set_public_readable(document_id: str, token: str | None = None) -> dict:
    """Allow anyone on the internet with the link to read, never edit."""
    access_token = token or get_token()
    return _request(
        "PATCH",
        f"/drive/v1/permissions/{document_id}/public?type=docx",
        access_token,
        json={
            "external_access": True,
            "link_share_entity": "anyone_readable",
        },
    )


def get_document_url(document_id: str, token: str | None = None) -> str:
    """Return the tenant-specific URL supplied by Feishu metadata."""
    access_token = token or get_token()
    result = _request(
        "POST",
        "/drive/v1/metas/batch_query",
        access_token,
        json={
            "request_docs": [
                {"doc_token": document_id, "doc_type": "docx"}
            ],
            "with_url": True,
        },
    )
    metas = result.get("data", {}).get("metas", [])
    if metas and metas[0].get("url"):
        return str(metas[0]["url"])
    return f"https://my.feishu.cn/docx/{document_id}"


def create_weekly_paper_document(
    papers: list[dict],
    start_date: str,
    end_date: str,
    topics: list[str],
    chat_id: str = "",
    document_title: str = "",
    existing_document_id: str = "",
) -> dict:
    token = get_token()
    title = document_title or f"AI 论文周报（图表版）｜{start_date}—{end_date}"
    document_id = str(existing_document_id or "").strip()
    is_new_document = not document_id
    if is_new_document:
        folder_token = os.getenv("FEISHU_PAPER_FOLDER_TOKEN", "").strip()
        create_body = {"title": title}
        if folder_token:
            create_body["folder_token"] = folder_token
        result = _request("POST", "/docx/v1/documents", token, json=create_body)
        document = result["data"]["document"]
        document_id = document["document_id"]

    from paper_media import prepare_paper_deep_images

    paper_images: list[list[dict]] = []
    for paper in papers:
        try:
            paper_images.append(prepare_paper_deep_images(paper))
        except Exception as exc:
            print(
                f"飞书文档论文图片生成失败: {paper.get('title', '')}: {exc}",
                flush=True,
            )
            paper_images.append([])

    date_label = start_date if start_date == end_date else f"{start_date}—{end_date}"
    intro_children = [
        _heading_block(f"{date_label}｜新增 {len(papers)} 篇", level=1),
        _text_block([_text_run(f"时间范围：{start_date} 至 {end_date}", bold=True)]),
        _text_block([_text_run(f"关注方向：{'、'.join(topics)}")]),
        _text_block(
            [
                _text_run(
                    "说明：标题、作者、摘要和链接来自 arXiv 或会议官方论文页；"
                    "机构和英文 Contributions 仅从论文官方 PDF 提取，"
                    "未明确提供时不会猜测。"
                )
            ]
        ),
    ]
    _request(
        "POST",
        f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
        token,
        json={"index": 0, "children": intro_children}
        if is_new_document
        else {"children": intro_children},
    )
    time.sleep(0.4)
    table_payload = _summary_table_payload(
        papers,
        index=_root_child_count(document_id, token),
    )
    table_id = table_payload["children_id"][0]
    _request(
        "POST",
        f"/docx/v1/documents/{document_id}/blocks/{document_id}/descendant",
        token,
        json=table_payload,
    )

    time.sleep(0.5)
    _fill_table_images(token, document_id, paper_images, table_id=table_id)

    for index, paper in enumerate(papers, start=1):
        title_text = format_latex_for_feishu(paper.get("title"))
        paper_url = str(paper.get("paper_url") or "").strip()
        code_url = str(paper.get("code_url") or "").strip()
        code_label = (
            "官方公开代码仓库（许可证待补充）"
            if str(paper.get("code_license_status") or "").casefold() == "pending"
            else "开源代码仓库（已三层核验）"
        )
        authors = "、".join(str(value) for value in paper.get("authors", []) if value)
        institutions = "、".join(
            str(value) for value in paper.get("institutions", []) if value
        )
        categories = "、".join(str(value) for value in paper.get("categories", []) if value)
        contributions = _list_values(paper.get("contributions"))
        original_contributions = _list_values(
            paper.get("contributions_original")
        )
        research_question = paper.get("research_question") or {}
        question_text = (
            str(research_question.get("text") or "")
            if isinstance(research_question, dict)
            else str(research_question or "")
        )
        question_source = (
            str(research_question.get("source") or "原文未明确")
            if isinstance(research_question, dict)
            else "原文未明确"
        )
        detail_children = [
                _heading_block(f"{index}. {title_text}", level=2),
                _text_block(
                    [
                        _text_run(f"推荐指数：{paper.get('score', '-')}/10　"),
                        _text_run(format_latex_for_feishu(paper.get("reason"))),
                    ]
                ),
                _text_block(
                    [_text_run("中文导读：" + format_latex_for_feishu(paper.get("summary")))]
                ),
                _text_block(
                    [
                        _text_run(
                            "English Guide："
                            + format_latex_for_feishu(
                                paper.get("summary_en") or "英文导读暂未生成。"
                            )
                        )
                    ]
                ),
                _heading_block("研究问题", level=3),
                _text_block(
                    [
                        _text_run(
                            (question_text or "原文未明确")
                            + f"\n[{'原文未明确' if question_source == '原文未明确' else '原文事实 · ' + question_source}]"
                        )
                    ]
                ),
                _text_block(
                    [
                        _text_run(
                            "主要方法："
                            + format_latex_for_feishu(
                                paper.get("main_method")
                                or "以论文摘要中的方法描述为准。"
                            )
                        )
                    ]
                ),
                _text_block([_text_run(f"作者：{authors}")]),
                _text_block(
                    [
                        _text_run(
                            "机构："
                            + (institutions or "官方 PDF 首页未明确提供")
                        )
                    ]
                ),
                _text_block(
                    [
                        _text_run(
                            f"提交日期：{str(paper.get('published') or '')[:10]}　"
                            f"分类：{categories}"
                        )
                    ]
                ),
            ]
        if contributions:
            detail_children.append(
                _text_block(
                    [_text_run("核心贡献：\n" + "\n".join(f"• {value}" for value in contributions))]
                )
            )
        else:
            detail_children.append(
                _text_block([_text_run("核心贡献：暂无可靠提炼，请以摘要原文为准。")])
            )
        if original_contributions:
            detail_children.append(
                _text_block(
                    [
                        _text_run(
                            "Contributions · 英文原文：\n"
                            + "\n".join(
                                f"{index}. {value}"
                                for index, value in enumerate(
                                    original_contributions,
                                    start=1,
                                )
                            )
                        )
                    ]
                )
            )
        core_insights = _core_insight_lines(paper.get("core_insights"))
        if core_insights:
            detail_children.extend(
                [
                    _heading_block("先看结论｜三个可带走的 Insight", level=3),
                    _text_block([_text_run("\n\n".join(core_insights))]),
                ]
            )
        deep_sections = [
            ("研究背景与动机", _sourced_lines(paper.get("background"))),
            ("方法与实验结果对应", _method_result_lines(paper.get("method_result_map"))),
            ("关键实验结果", _sourced_lines(paper.get("key_results"))),
            ("证据链与论证顺序", _sourced_lines(paper.get("evidence_chain"))),
            ("讨论亮点", _sourced_lines(paper.get("discussion_highlights"))),
            ("作者明确局限", _sourced_lines(paper.get("limitations"))),
            ("写作拆解", _sourced_lines(paper.get("writing_notes"))),
            ("建议阅读路径", _sourced_lines(paper.get("reading_guide"))),
        ]
        for heading, lines in deep_sections:
            if not lines:
                continue
            detail_children.extend(
                [
                    _heading_block(heading, level=3),
                    _text_block([_text_run("\n".join(lines))]),
                ]
            )
        images = paper_images[index - 1] if index - 1 < len(paper_images) else []
        if images:
            detail_children.append(
                _heading_block("核心图证据｜看图时要抓住什么", level=2)
            )
        time.sleep(0.4)
        _request(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            token,
            json={"children": detail_children},
        )
        if images:
            _append_deep_images(token, document_id, paper, images)
        _request(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            token,
            json={
                "children": [
                    _heading_block("摘要 · 中文翻译", level=3),
                    _text_block(
                        [
                            _text_run(
                                format_latex_for_feishu(
                                    paper.get("abstract_zh") or "中文翻译暂未生成。"
                                )
                            )
                        ]
                    ),
                    _heading_block("Abstract · English Original", level=3),
                    _text_block(
                        [_text_run(format_latex_for_feishu(paper.get("abstract")))]
                    ),
                    *(
                        [
                            _text_block(
                                [
                                    _text_run(
                                        code_label,
                                        bold=True,
                                        link=code_url,
                                    )
                                ]
                            )
                        ]
                        if code_url
                        else []
                    ),
                    _text_block([_text_run("论文官方页", bold=True, link=paper_url)]),
                    {"block_type": 22, "divider": {}},
                ]
            },
        )

    if chat_id:
        _request(
            "POST",
            f"/drive/v1/permissions/{document_id}/members"
            "?type=docx&need_notification=false",
            token,
            json={"member_type": "openchat", "member_id": chat_id, "perm": "view"},
        )

    set_public_readable(document_id, token)
    document_url = get_document_url(document_id, token)

    return {
        "document_id": document_id,
        "title": title,
        "url": document_url,
    }
