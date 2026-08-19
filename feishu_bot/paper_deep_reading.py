from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from automation_llm import call_automation_llm as call_glm
from paper_media import (
    _download_pdf,
    _safe_cache_id,
    _validated_pdf_url,
    prepare_paper_deep_images,
)


CACHE_DIR = Path("data/paper_analysis")
MAX_PAGES = 16
MAX_TEXT_CHARS = 55_000
LIST_FIELDS = (
    "background",
    "method_result_map",
    "key_results",
    "evidence_chain",
    "discussion_highlights",
    "limitations",
    "writing_notes",
)


def _parse_json_object(value: str) -> dict:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1], strict=False)
        raise


def extract_numbered_pdf_text(pdf_url: str) -> tuple[str, int]:
    """Extract readable PDF text with explicit page markers for source labels."""
    content = _download_pdf(pdf_url)
    document = fitz.open(stream=content, filetype="pdf")
    try:
        pages = []
        for index in range(min(document.page_count, MAX_PAGES)):
            text = document.load_page(index).get_text("text")
            text = text.replace("\u00ad", "")
            text = re.sub(r"([A-Za-z])-\s*\n\s*([a-z])", r"\1\2", text)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if text:
                pages.append(f"[PDF p.{index + 1}]\n{text}")
            if sum(len(value) for value in pages) >= MAX_TEXT_CHARS:
                break
        return "\n\n".join(pages)[:MAX_TEXT_CHARS], document.page_count
    finally:
        document.close()


def _fact_item(value: object, *, default_source: str = "原文未明确") -> dict:
    if isinstance(value, dict):
        text = str(value.get("text") or "").strip()
        source = str(value.get("source") or default_source).strip()
    else:
        text = str(value or "").strip()
        source = default_source
    return {"text": text, "source": source or default_source}


def _method_result_item(value: object) -> dict:
    if not isinstance(value, dict):
        return {"method": str(value or "").strip(), "result": "", "source": "原文未明确"}
    return {
        "method": str(value.get("method") or "").strip(),
        "result": str(value.get("result") or "").strip(),
        "source": str(value.get("source") or "原文未明确").strip(),
    }


def _core_insight_item(value: object) -> dict:
    if not isinstance(value, dict):
        return {
            "finding": str(value or "").strip(),
            "why_it_matters": "",
            "transfer": "",
            "source": "原文未明确",
        }
    return {
        "finding": str(value.get("finding") or "").strip(),
        "why_it_matters": str(value.get("why_it_matters") or "").strip(),
        "transfer": str(value.get("transfer") or "").strip(),
        "source": str(value.get("source") or "原文未明确").strip(),
    }


def _figure_insight_item(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    try:
        figure_number = int(value.get("figure_number") or 0)
    except (TypeError, ValueError):
        figure_number = 0
    return {
        "figure_number": figure_number,
        "what_it_shows": str(value.get("what_it_shows") or "").strip(),
        "why_it_matters": str(value.get("why_it_matters") or "").strip(),
        "reading_tip": str(value.get("reading_tip") or "").strip(),
        "source": str(value.get("source") or "原文未明确").strip(),
    }


def normalize_deep_reading(payload: dict, paper: dict) -> dict:
    result = dict(paper)
    summary = re.sub(r"\s+", " ", str(payload.get("summary") or "")).strip()
    if summary:
        result["summary"] = summary[:520]
    summary_en = re.sub(r"\s+", " ", str(payload.get("summary_en") or "")).strip()
    abstract_zh = re.sub(r"\s+", " ", str(payload.get("abstract_zh") or "")).strip()
    if summary_en:
        result["summary_en"] = summary_en
    if abstract_zh:
        result["abstract_zh"] = abstract_zh
    if summary_en and abstract_zh:
        result["bilingual_source"] = "official_pdf_and_abstract"

    result["research_question"] = _fact_item(payload.get("research_question"))
    for field in LIST_FIELDS:
        values = payload.get(field) or []
        if not isinstance(values, list):
            values = [values]
        if field == "method_result_map":
            normalized = [_method_result_item(value) for value in values]
            normalized = [value for value in normalized if value["method"]]
        else:
            source = "编辑解读" if field == "writing_notes" else "原文未明确"
            normalized = [_fact_item(value, default_source=source) for value in values]
            normalized = [value for value in normalized if value["text"]]
        result[field] = normalized[:5]
    core_insights = payload.get("core_insights") or []
    if not isinstance(core_insights, list):
        core_insights = [core_insights]
    result["core_insights"] = [
        item
        for item in (_core_insight_item(value) for value in core_insights)
        if item["finding"]
    ][:3]
    figure_insights = payload.get("figure_insights") or []
    if not isinstance(figure_insights, list):
        figure_insights = [figure_insights]
    result["figure_insights"] = [
        item
        for item in (_figure_insight_item(value) for value in figure_insights)
        if item.get("figure_number") and item.get("what_it_shows")
    ][:5]
    reading_guide = payload.get("reading_guide") or []
    if not isinstance(reading_guide, list):
        reading_guide = [reading_guide]
    result["reading_guide"] = [
        item
        for item in (
            _fact_item(value, default_source="编辑解读")
            for value in reading_guide
        )
        if item["text"]
    ][:4]
    result["deep_reading_source"] = "official_pdf"
    return result


def _fallback(paper: dict, reason: str = "") -> dict:
    result = dict(paper)
    task = str(result.get("task") or "").strip()
    result.setdefault(
        "research_question",
        {"text": task, "source": "Abstract" if task else "原文未明确"},
    )
    for field in LIST_FIELDS:
        result.setdefault(field, [])
    for field in ("core_insights", "figure_insights", "reading_guide"):
        result.setdefault(field, [])
    result["deep_reading_source"] = "abstract_fallback"
    if reason:
        result["deep_reading_error"] = reason[:300]
    return result


def enrich_deep_reading(paper: dict) -> dict:
    """Create an evidence-labelled reading breakdown from the official PDF."""
    cache_id = _safe_cache_id(paper)
    pdf_url = _validated_pdf_url(paper)
    if not cache_id or not pdf_url:
        return _fallback(paper, "缺少可信 PDF")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{cache_id}-deep-reading-v4.json"
    if cache_path.exists():
        try:
            return normalize_deep_reading(
                json.loads(cache_path.read_text(encoding="utf-8")),
                paper,
            )
        except (OSError, ValueError, TypeError):
            pass

    try:
        try:
            figures = prepare_paper_deep_images(paper)
        except Exception as exc:
            print(f"深度解析图片上下文获取失败: {paper.get('title', '')}: {exc}", flush=True)
            figures = []
        figure_context = "\n".join(
            f"- Figure {item.get('figure_number')}（PDF p.{item.get('page_number')}，"
            f"类型：{item.get('kind')}）：{item.get('caption')}"
            for item in figures
        ) or "- 未提取到可核验图片"
        pdf_text, page_count = extract_numbered_pdf_text(pdf_url)
        if len(pdf_text) < 1500:
            return _fallback(paper, "PDF 正文文本不足")
        prompt = f"""
你是严格、审慎的科研论文阅读编辑。请只依据下面提供的官方论文 PDF 文本，
为飞书论文卡片和论文库生成结构化中文拆解。不得使用外部知识，不得猜测；
原文没有明确证据的字段必须返回空数组或将 source 写为“原文未明确”。

论文标题：{paper.get('title', '')}
PDF 总页数：{page_count}
官方摘要：{paper.get('abstract') or paper.get('summary') or ''}

本次图文精读选中的完整图片及原文 Caption：
{figure_context}

PDF 文本（每页以 [PDF p.N] 标记）：
{pdf_text}

严格返回 JSON 对象，不要 Markdown：
{{
  "summary": "260至340个中文字符（不要过短），依次说明研究问题、核心方案、关键结果和阅读价值；数字必须来自原文",
  "summary_en": "100 to 160 English words that convey the same problem, method, result and reading value as summary; preserve the same claim strength",
  "abstract_zh": "官方英文 Abstract 的完整忠实中文翻译；逐句覆盖，不删减，不新增，保留数字、公式、缩写和术语",
  "research_question": {{"text": "作者要解决的核心问题或研究假设", "source": "Abstract / PDF p.N / Sec. N"}},
  "background": [{{"text": "领域背景、现有不足或研究动机", "source": "PDF p.N / Sec. N"}}],
  "method_result_map": [{{"method": "方法模块", "result": "与其对应的实验或结果；原文未明确对应关系时留空", "source": "PDF p.N / Sec. N / Table N / Figure N"}}],
  "key_results": [{{"text": "关键实验结果，保留有依据的数字和比较对象", "source": "PDF p.N / Table N / Figure N"}}],
  "evidence_chain": [{{"text": "作者按什么顺序用证据支持结论", "source": "PDF p.N / Sec. N"}}],
  "discussion_highlights": [{{"text": "作者在 Discussion/Conclusion 明确强调的亮点", "source": "PDF p.N / Sec. N"}}],
  "limitations": [{{"text": "作者明确承认的局限；没有就不要生成", "source": "PDF p.N / Sec. N"}}],
  "writing_notes": [{{"text": "可借鉴的论证或章节组织方式", "source": "编辑解读 · 基于 PDF p.N / Sec. N"}}],
  "core_insights": [{{
    "finding": "最值得记住的、由原文证据支持的结论",
    "why_it_matters": "为什么这个结论重要；明确写成编辑解读，不夸大",
    "transfer": "可迁移到其他研究或工程中的具体启示；条件不充分时写适用边界",
    "source": "PDF p.N / Table N / Figure N"
  }}],
  "figure_insights": [{{
    "figure_number": 1,
    "what_it_shows": "这张入选图片客观展示了什么",
    "why_it_matters": "它如何支持论文主张；属于编辑解读",
    "reading_tip": "读图时最应该比较的区域、曲线、列或案例",
    "source": "PDF p.N / Figure N"
  }}],
  "reading_guide": [{{
    "text": "建议按什么顺序阅读哪些章节/图表，以及原因",
    "source": "编辑解读 · 基于 PDF p.N / Figure N / Table N"
  }}]
}}
core_insights 最多3项，figure_insights 只为上面列出的入选图片生成且最多5项，
其他数组最多3项；事实 source 必须具体，不能写“论文原文”等模糊来源。
所有 why_it_matters、transfer、reading_tip 都是编辑解读，必须克制并说明适用边界，
不能把相关性写成因果，不能把单一数据集结果泛化为普遍结论。
"""
        payload = _parse_json_object(call_glm(prompt, timeout=360, web_search=False))
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return normalize_deep_reading(payload, paper)
    except Exception as exc:
        print(f"论文深度拆解失败，使用摘要降级: {paper.get('title', '')}: {exc}", flush=True)
        return _fallback(paper, str(exc))


def enrich_deep_readings(papers: list[dict]) -> list[dict]:
    return [enrich_deep_reading(paper) for paper in papers]
