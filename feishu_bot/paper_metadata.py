from __future__ import annotations

import re
import time
from typing import Iterable
from urllib.parse import urlparse

import fitz
import requests


MAX_PDF_BYTES = 64 * 1024 * 1024
AFFILIATION_WORDS = re.compile(
    r"\b(?:university|universit[aà-ÿ]*|institute|institution|laborator(?:y|ies)|lab\.?|"
    r"department|school|college|academy|centre|center|hospital|research|"
    r"corporation|company|inc\.?|ltd\.?|gmbh|deepmind|openai|nvidia|meta ai|"
    r"microsoft|google|amazon|bytedance|alibaba|tencent|tsinghua|peking|"
    r"galaxea ai|tiiis|iiis|cnrs|inria|eth z[uü]rich|epfl|mit|cmu)\b",
    re.IGNORECASE,
)
STOP_LINE = re.compile(
    r"^(?:abstract|introduction|keywords?|index terms?|1\.?\s+introduction)\b",
    re.IGNORECASE,
)
NON_AFFILIATION = re.compile(
    r"(?:equal contribution|corresponding author|project page|code:|arxiv:|"
    r"https?://|www\.|@\w+[.-]\w+)",
    re.IGNORECASE,
)
PROSE_LINE = re.compile(
    r"^(?:in this (?:work|paper)|we\s|this (?:work|paper)|our (?:method|model|approach))\b",
    re.IGNORECASE,
)
SUPERSCRIPT_TRANSLATION = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
GENERIC_AFFILIATIONS = {
    "university",
    "institute",
    "institution",
    "laboratory",
    "laboratories",
    "lab",
    "department",
    "school",
    "college",
    "academy",
    "centre",
    "center",
    "research",
}
TRAILING_LOCATION = re.compile(
    r",\s*(?:USA|United States|Canada|Switzerland|China|Japan|Korea|France|"
    r"Germany|United Kingdom|UK|Singapore|Australia|India|Israel|Spain|Italy|"
    r"Netherlands|Belgium|Austria|Sweden|Norway|Denmark|Finland)\.?$",
    re.IGNORECASE,
)
CONTRIBUTION_STARTS = [
    re.compile(
        r"(?:in summary,\s*)?(?:the|our)?\s*(?:key|core|main)?\s*"
        r"contributions(?:\s+of\s+(?:this paper|[A-Za-z0-9-]+))?\s+"
        r"(?:are(?:\s+summarized)?(?:\s+as\s+follows)?|can be summarized as follows)"
        r"\s*[:,]?\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"we\s+(?:make|summarize)\s+the\s+following\s+contributions\s*[:,]?\s*",
        re.IGNORECASE,
    ),
]
NEXT_SECTION = re.compile(
    r"\s+\d+(?:\.\d+)*\s+(?:related work|method|methodology|approach|"
    r"background|experiments?|implementation|results?|discussion|conclusion)\b",
    re.IGNORECASE,
)


def _clean_line(value: object) -> str:
    text = str(value or "").translate(SUPERSCRIPT_TRANSLATION)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[\s\d,*†‡§¶#\[\](){}]+", "", text).strip()
    return text.strip(" ,;|")


def _identity(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _looks_like_author_line(line: str, authors: Iterable[str]) -> bool:
    normalized = _identity(line)
    if not normalized:
        return False
    for author in authors:
        full_name = _identity(author)
        if len(full_name) >= 5 and full_name in normalized:
            return True
        parts = re.findall(r"[A-Za-zÀ-ÿ]+", str(author))
        if parts:
            surname = _identity(parts[-1])
            if len(surname) >= 4 and surname in normalized:
                return True
    return False


def _matching_author_count(line: str, authors: Iterable[str]) -> int:
    normalized = _identity(line)
    return sum(
        1
        for author in authors
        if len(_identity(author)) >= 5 and _identity(author) in normalized
    )


def _split_numbered_affiliations(line: str) -> list[str]:
    translated = line.translate(SUPERSCRIPT_TRANSLATION)
    parts = re.split(r"(?=\s*(?:\[\d{1,2}\]|\d{1,2})\s*(?=[A-ZÀ-Þ]))", translated)
    return [part.strip() for part in parts if part.strip()]


def extract_institutions_from_text(
    text: str,
    authors: Iterable[str] = (),
) -> list[str]:
    """Conservatively extract affiliations printed before the first-page abstract."""
    lines = [_clean_line(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []

    abstract_index = next(
        (index for index, line in enumerate(lines) if STOP_LINE.match(line)),
        min(len(lines), 90),
    )
    author_indexes = [
        index
        for index, line in enumerate(lines[:abstract_index])
        if _looks_like_author_line(line, authors)
        and not NON_AFFILIATION.search(line)
        and not AFFILIATION_WORDS.search(line)
    ]
    start = max(author_indexes) + 1 if author_indexes else 1

    candidates: list[str] = []
    for line in lines[:abstract_index]:
        if "," not in line or _matching_author_count(line, authors) != 1:
            continue
        if not _looks_like_author_line(line, authors):
            continue
        if NON_AFFILIATION.search(line):
            continue
        remainder = line.split(",", 1)[1]
        for part in re.split(r"\s+and\s+", remainder, flags=re.IGNORECASE):
            candidate = TRAILING_LOCATION.sub("", _clean_line(part)).strip(" ,;")
            if candidate and AFFILIATION_WORDS.search(candidate):
                candidates.append(candidate)

    for line in lines[start:min(abstract_index, start + 16)]:
        for part in _split_numbered_affiliations(line):
            candidate = _clean_line(part)
            if not candidate or len(candidate) > 240:
                continue
            if _looks_like_author_line(candidate, authors):
                continue
            if NON_AFFILIATION.search(candidate):
                continue
            if PROSE_LINE.search(candidate):
                continue
            if not AFFILIATION_WORDS.search(candidate):
                continue
            candidates.append(candidate)

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _identity(candidate)
        if len(key) < 3 or candidate.casefold().rstrip(".") in GENERIC_AFFILIATIONS:
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result[:8]


def _normalize_pdf_prose(text: str) -> str:
    value = str(text or "").replace("\u00ad", "")
    value = re.sub(
        r"([A-Za-z][A-Za-z-]*)-\s*\n\s*([a-z])",
        lambda match: (
            match.group(1)
            + ("-" if "-" in match.group(1) else "")
            + match.group(2)
        ),
        value,
    )
    return re.sub(r"\s+", " ", value).strip()


def extract_original_contributions_from_text(text: str) -> list[str]:
    """Extract verbatim English contribution claims, normalizing PDF line wraps only."""
    prose = _normalize_pdf_prose(text)
    start_match = next(
        (match for pattern in CONTRIBUTION_STARTS if (match := pattern.search(prose))),
        None,
    )
    if not start_match:
        return []

    block = prose[start_match.end(): start_match.end() + 5000]
    end_match = NEXT_SECTION.search(block)
    if end_match:
        block = block[:end_match.start()]
    block = block.strip(" ,;:")
    if not block:
        return []

    bullets: list[str] = []
    if "•" in block:
        bullets = [part.strip() for part in block.split("•") if part.strip()]
    else:
        markers = list(re.finditer(r"(?<!\w)\(?([1-6])\)\s+", block))
        if markers and markers[0].start() < 20:
            for index, marker in enumerate(markers):
                end = markers[index + 1].start() if index + 1 < len(markers) else len(block)
                bullets.append(block[marker.end():end].strip())

    if not bullets:
        bullets = re.split(r"(?<=[.!?])\s+(?=[A-Z])", block)

    result = []
    for bullet in bullets:
        value = re.sub(r"^(?:and\s+)?", "", bullet.strip(" ,;:"), flags=re.IGNORECASE)
        value = re.sub(r"[,;]?\s+and$", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip()
        if len(value) < 20:
            continue
        result.append(value)
    return result[:5]


def extract_pdf_metadata(
    pdf_url: str,
    authors: Iterable[str] = (),
) -> dict[str, list[str]]:
    parsed = urlparse(str(pdf_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"institutions": [], "contributions_original": []}

    content = b""
    for attempt in range(3):
        response = requests.get(
            pdf_url,
            timeout=45,
            headers={"User-Agent": "HumanGroupBot/1.0 (paper metadata verifier)"},
        )
        response.raise_for_status()
        content = response.content
        if content.startswith(b"%PDF") and len(content) <= MAX_PDF_BYTES:
            break
        if attempt < 2:
            time.sleep(attempt + 1)
    if not content.startswith(b"%PDF") or len(content) > MAX_PDF_BYTES:
        return {"institutions": [], "contributions_original": []}

    document = fitz.open(stream=content, filetype="pdf")
    try:
        if document.page_count < 1:
            return {"institutions": [], "contributions_original": []}
        first_page_text = document.load_page(0).get_text("text")
        opening_text = "\n".join(
            document.load_page(index).get_text("text")
            for index in range(min(4, document.page_count))
        )
    finally:
        document.close()
    return {
        "institutions": extract_institutions_from_text(first_page_text, authors),
        "contributions_original": extract_original_contributions_from_text(opening_text),
    }


def extract_institutions_from_pdf(
    pdf_url: str,
    authors: Iterable[str] = (),
) -> list[str]:
    return extract_pdf_metadata(pdf_url, authors)["institutions"]


def enrich_paper_metadata(paper: dict) -> dict:
    """Add official-PDF affiliations without replacing verified source fields."""
    result = dict(paper)
    current = [
        str(value).strip()
        for value in result.get("institutions", [])
        if str(value).strip()
    ]
    original_contributions = [
        str(value).strip()
        for value in result.get("contributions_original", [])
        if str(value).strip()
    ]
    if current and original_contributions:
        result["institutions"] = current
        result["contributions_original"] = original_contributions
        return result

    pdf_url = str(result.get("pdf_url") or "").strip()
    arxiv_id = str(result.get("id") or result.get("arxiv_id") or "").strip()
    if not pdf_url and re.fullmatch(r"\d{4}\.\d{4,5}", arxiv_id):
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

    try:
        metadata = extract_pdf_metadata(
            pdf_url,
            result.get("authors", []),
        )
    except Exception as exc:
        print(
            f"论文机构提取失败，保留官方未提供状态: {result.get('title', '')}: {exc}",
            flush=True,
        )
        metadata = {"institutions": [], "contributions_original": []}

    institutions = current or metadata["institutions"]
    contributions_original = (
        original_contributions or metadata["contributions_original"]
    )

    result["institutions"] = institutions
    result["institutions_source"] = (
        "official_pdf_first_page" if institutions else "not_available"
    )
    result["contributions_original"] = contributions_original
    result["contributions_original_source"] = (
        "official_pdf" if contributions_original else "not_available"
    )
    return result


def enrich_papers_metadata(papers: Iterable[dict]) -> list[dict]:
    return [enrich_paper_metadata(paper) for paper in papers]
