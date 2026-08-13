from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from glm_client import call_glm


CACHE_DIR = Path("data/paper_analysis")


def _cache_id(paper: dict) -> str:
    identity = "|".join(
        [
            str(paper.get("id") or paper.get("arxiv_id") or "").strip(),
            str(paper.get("title") or "").strip(),
            str(paper.get("abstract") or "").strip(),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _parse_json_object(value: str) -> dict:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def _has_chinese(value: object) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))


def normalize_bilingual_fields(payload: dict, paper: dict) -> dict:
    result = dict(paper)
    summary_zh = re.sub(r"\s+", " ", str(payload.get("summary_zh") or "")).strip()
    summary_en = re.sub(r"\s+", " ", str(payload.get("summary_en") or "")).strip()
    abstract_zh = re.sub(r"\s+", " ", str(payload.get("abstract_zh") or "")).strip()
    if summary_zh and not _has_chinese(result.get("summary")):
        result["summary"] = summary_zh
    if summary_en:
        result["summary_en"] = summary_en
    if abstract_zh:
        result["abstract_zh"] = abstract_zh
    result["bilingual_source"] = "official_abstract"
    return result


def enrich_bilingual_fields(paper: dict) -> dict:
    """Add a paired English guide and faithful Chinese abstract translation."""
    if (
        str(paper.get("summary_en") or "").strip()
        and str(paper.get("abstract_zh") or "").strip()
        and _has_chinese(paper.get("summary"))
    ):
        result = dict(paper)
        result.setdefault("bilingual_source", "official_abstract")
        return result

    abstract = str(paper.get("abstract") or "").strip()
    if not abstract:
        return paper
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{_cache_id(paper)}-bilingual-v1.json"
    if cache_path.exists():
        try:
            return normalize_bilingual_fields(
                json.loads(cache_path.read_text(encoding="utf-8")), paper
            )
        except (OSError, TypeError, ValueError):
            pass

    prompt = f"""
你是严谨的科研双语编辑。只能依据下方论文标题、官方英文 Abstract 和已有中文导读，
不得联网、不得补充原文没有的信息。请生成中英对照内容。

标题：{paper.get('title', '')}
已有中文导读：{paper.get('summary', '')}
官方英文 Abstract：
{abstract}

严格返回 JSON 对象，不要 Markdown：
{{
  "summary_zh": "220至340个中文字符的导读，覆盖问题、方法、关键结果与阅读价值；数字严格忠于 Abstract",
  "summary_en": "100 to 160 English words conveying the same points and strength of claims as summary_zh, written as a reading guide rather than copying the Abstract",
  "abstract_zh": "对官方 Abstract 的完整、忠实中文翻译；不删减句子，不新增结论，保留数字、公式、缩写和专有名词"
}}
summary_zh 与 summary_en 必须语义对齐；abstract_zh 必须逐句覆盖完整 Abstract。
"""
    try:
        payload = _parse_json_object(
            call_glm(prompt, timeout=240, web_search=False)
        )
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return normalize_bilingual_fields(payload, paper)
    except Exception as exc:
        result = dict(paper)
        result["bilingual_error"] = str(exc)[:300]
        return result


def enrich_bilingual_papers(papers: list[dict]) -> list[dict]:
    return [enrich_bilingual_fields(paper) for paper in papers]
