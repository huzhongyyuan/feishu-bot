from __future__ import annotations

import json
import hashlib
import io
import math
import os
import re
import time
import urllib.parse
from pathlib import Path

import fitz
import requests
from PIL import Image


CACHE_DIR = Path("data/paper_media")
MAX_PDF_BYTES = 96 * 1024 * 1024
MAX_PDF_DOWNLOAD_SECONDS = 300
MAX_FIGURE_SCAN_PAGES = 12
TEASER_ASPECT_RATIO = 2.0
CAPTION_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:figure|fig\.?)\s*(\d+)\s*(?:[.:]|\s)",
    re.I,
)
ARCHITECTURE_KEYWORDS = {
    "architecture": 12,
    "framework": 10,
    "pipeline": 9,
    "network": 8,
    "overview": 8,
    "method": 6,
    "approach": 5,
    "model": 4,
    "system": 4,
    "workflow": 4,
    "module": 8,
    "component": 7,
    "compression": 7,
    "mechanism": 6,
    "correspondence": 5,
    "design": 5,
    "attention": 4,
}
NON_ARCHITECTURE_KEYWORDS = {
    "qualitative": 12,
    "scaling": 10,
    "pca": 9,
    "ablation": 8,
    "comparison": 6,
    "results": 5,
    "plot": 5,
    "frames": 10,
    "clips": 10,
    "emotion": 8,
    "facial": 7,
    "smiling": 7,
    "open-mouth": 7,
    "selected examples": 6,
    "graph": 9,
    "chart": 9,
    "curve": 8,
    "heatmap": 8,
    "t-sne": 8,
}
STRONG_ARCHITECTURE_KEYWORDS = {
    "architecture",
    "framework",
    "pipeline",
    "network",
    "overview",
    "workflow",
    "module",
    "system",
    "method",
    "compression",
    "correspondence",
}
MIN_ARCHITECTURE_SCORE = 8
EXPLICIT_ARCHITECTURE_KEYWORDS = {
    "architecture",
    "framework",
    "pipeline",
    "workflow",
    "network diagram",
    "system diagram",
    "method overview",
    "model overview",
}
METHOD_CONTEXT_KEYWORDS = {
    "architecture",
    "framework",
    "pipeline",
    "workflow",
    "method",
    "approach",
    "model",
    "system",
    "network",
    "training",
    "inference",
}
MODULE_CONTEXT_KEYWORDS = {
    "encoder",
    "decoder",
    "generator",
    "module",
    "component",
    "input",
    "output",
    "conditioning",
    "branch",
    "stage",
    "backbone",
    "layer",
    "token",
}
TEASER_KEYWORDS = {
    "teaser": 20,
    "qualitative": 14,
    "visual results": 13,
    "visualization": 10,
    "generated": 8,
    "generation results": 10,
    "examples": 6,
    "results": 5,
}
RESULT_KEYWORDS = {
    "result": 10,
    "results": 10,
    "comparison": 10,
    "compare": 8,
    "quantitative": 10,
    "benchmark": 9,
    "performance": 8,
    "evaluation": 7,
    "accuracy": 6,
    "error": 5,
    "success rate": 7,
    "user study": 7,
}
ABLATION_KEYWORDS = {
    "ablation": 15,
    "component": 7,
    "variant": 6,
    "effect of": 7,
    "analysis of": 5,
    "study on": 5,
}
QUALITATIVE_KEYWORDS = {
    "qualitative": 15,
    "visual comparison": 12,
    "visualization": 8,
    "generated": 5,
    "generation results": 10,
    "examples": 5,
    "failure case": 9,
}
TRUSTED_PDF_HOSTS = {
    "arxiv.org",
    "export.arxiv.org",
    "openaccess.thecvf.com",
    "openreview.net",
    "proceedings.mlr.press",
    "icml.cc",
}


def _safe_cache_id(paper: dict) -> str:
    value = str(paper.get("id") or paper.get("paper_url") or "")
    match = re.search(r"(\d{4}\.\d{4,5})", value)
    if match:
        return match.group(1)
    identity = "|".join(
        [
            str(paper.get("title") or "").strip(),
            str(paper.get("pdf_url") or "").strip(),
        ]
    )
    if not identity.strip("|"):
        return ""
    return "official-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _validated_pdf_url(paper: dict) -> str:
    value = str(paper.get("pdf_url") or "").strip()
    if not value:
        paper_url = str(paper.get("paper_url") or "").strip()
        if ".pdf" in paper_url.casefold():
            value = paper_url
    parsed = urllib.parse.urlparse(value)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in TRUSTED_PDF_HOSTS:
        return ""
    return value


def _download_pdf(url: str) -> bytes:
    proxy_url = os.getenv("PAPER_PROXY_URL", os.getenv("HF_PROXY_URL", "")).strip()
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    started = time.monotonic()
    response = requests.get(
        url,
        timeout=(20, 180),
        headers={"User-Agent": "HumanGroupBot/1.0 paper figure extractor"},
        proxies=proxies,
        stream=True,
    )
    response.raise_for_status()
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=256 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_PDF_BYTES:
            raise RuntimeError("论文 PDF 超过 96 MB，跳过图片生成")
        if time.monotonic() - started > MAX_PDF_DOWNLOAD_SECONDS:
            raise RuntimeError("论文 PDF 下载超过 300 秒，跳过图片生成")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content.startswith(b"%PDF"):
        raise RuntimeError("论文地址未返回 PDF")
    return content


def _horizontal_overlap(left: fitz.Rect, right: fitz.Rect) -> float:
    overlap = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    denominator = max(1.0, min(left.width, right.width))
    return overlap / denominator


def _text_blocks(page: fitz.Page) -> list[tuple]:
    return [
        block
        for block in page.get_text("blocks")
        if len(block) >= 7 and block[6] == 0 and str(block[4]).strip()
    ]


def _caption_candidates(page: fitz.Page, page_index: int) -> list[dict]:
    candidates = []
    blocks = sorted(_text_blocks(page), key=lambda value: (value[1], value[0]))
    for block in blocks:
        raw_text = str(block[4]).strip()
        match = CAPTION_PATTERN.search(raw_text)
        if not match:
            continue
        caption = re.sub(r"\s+", " ", raw_text[match.start():]).strip()
        caption_rect = fitz.Rect(block[:4])
        # PyMuPDF often splits the first caption line from the remaining lines.
        # Join only an immediately adjacent block in the same column.
        continuation = None
        for next_block in blocks:
            next_rect = fitz.Rect(next_block[:4])
            vertical_gap = next_rect.y0 - caption_rect.y1
            if not (-0.5 <= vertical_gap <= 4.0):
                continue
            if abs(next_rect.x0 - caption_rect.x0) > 12:
                continue
            if next_rect.width < caption_rect.width * 0.7:
                continue
            next_text = re.sub(r"\s+", " ", str(next_block[4])).strip()
            if not next_text or CAPTION_PATTERN.search(str(next_block[4])):
                continue
            continuation = (next_rect, next_text)
            break
        if continuation:
            next_rect, next_text = continuation
            caption = f"{caption} {next_text}"
            caption_rect |= next_rect
        candidates.append(
            {
                "page_index": page_index,
                "number": int(match.group(1)),
                "caption": caption,
                "caption_rect": caption_rect,
            }
        )
    # Body prose sometimes starts with "Figure N shows/provides ...". When the
    # real caption is also present on the page, prefer the formal punctuated
    # "Figure N." / "Figure N:" block and keep each figure number only once.
    best_by_number: dict[int, dict] = {}
    for candidate in candidates:
        number = int(candidate["number"])
        caption = str(candidate.get("caption") or "")
        strict = bool(
            re.match(
                rf"\s*(?:figure|fig\.?)\s*{number}\s*[.:]",
                caption,
                re.I,
            )
        )
        candidate["caption_confidence"] = 2 if strict else 1
        previous = best_by_number.get(number)
        if previous is None or candidate["caption_confidence"] > previous.get(
            "caption_confidence", 0
        ):
            best_by_number[number] = candidate
    return list(best_by_number.values())


def _figure_scope(page: fitz.Page, caption: fitz.Rect) -> fitz.Rect:
    """Return full column/page bounds so multi-panel figures are never halved."""
    page_rect = page.rect
    center_distance = abs(caption.x0 + caption.x1 - page_rect.x0 - page_rect.x1) / 2
    full_width = (
        caption.width >= page_rect.width * 0.52
        or (
            caption.width >= page_rect.width * 0.42
            and center_distance <= page_rect.width * 0.12
        )
    )
    margin = 14
    if full_width:
        return fitz.Rect(
            page_rect.x0 + margin,
            page_rect.y0,
            page_rect.x1 - margin,
            page_rect.y1,
        )

    middle = (page_rect.x0 + page_rect.x1) / 2
    gutter = 5
    caption_center = (caption.x0 + caption.x1) / 2
    if caption_center < middle:
        return fitz.Rect(page_rect.x0 + margin, page_rect.y0, middle - gutter, page_rect.y1)
    return fitz.Rect(middle + gutter, page_rect.y0, page_rect.x1 - margin, page_rect.y1)


def _graphic_rects(page: fitz.Page) -> list[fitz.Rect]:
    page_area = max(1.0, page.rect.width * page.rect.height)
    rectangles: list[fitz.Rect] = []
    try:
        for info in page.get_image_info(xrefs=True):
            rect = fitz.Rect(info.get("bbox", (0, 0, 0, 0)))
            if not rect.is_empty and rect.width * rect.height >= page_area * 0.0005:
                rectangles.append(rect)
    except Exception:
        pass
    try:
        for drawing in page.get_drawings():
            rect = fitz.Rect(drawing.get("rect", (0, 0, 0, 0)))
            if not rect.is_empty and rect.width * rect.height >= 4:
                rectangles.append(rect)
    except Exception:
        pass
    return rectangles


def _find_complete_figure_crop(page: fitz.Page, figure: dict) -> fitz.Rect | None:
    """Locate a whole figure plus caption, including raster tiles and vectors."""
    page_rect = page.rect
    caption = figure["caption_rect"]
    scope = _figure_scope(page, caption)
    # Always include the complete caption block. Two-column PDFs frequently
    # place the caption a few points into the gutter; hard column bounds would
    # otherwise shave off its first/last characters and sometimes the plot too.
    scope = fitz.Rect(
        max(page_rect.x0 + 4, min(scope.x0, caption.x0 - 8)),
        scope.y0,
        min(page_rect.x1 - 4, max(scope.x1, caption.x1 + 8)),
        scope.y1,
    )
    earliest = max(page_rect.y0 + 14, caption.y0 - page_rect.height * 0.58)

    # A previous caption is a hard boundary when figures are stacked on one page.
    previous_caption_bottom = earliest
    for candidate in _caption_candidates(page, figure["page_index"]):
        rect = candidate["caption_rect"]
        if rect.y1 < caption.y0 - 5 and _horizontal_overlap(rect, scope) >= 0.35:
            previous_caption_bottom = max(previous_caption_bottom, rect.y1 + 6)

    # Long prose marks the end of the paragraph preceding the figure. Short
    # labels inside architecture diagrams are deliberately ignored.
    prose_bottom = previous_caption_bottom
    for block in _text_blocks(page):
        rect = fitz.Rect(block[:4])
        text = re.sub(r"\s+", " ", str(block[4])).strip()
        if rect.y1 >= caption.y0 - 5 or rect.y1 <= earliest:
            continue
        if CAPTION_PATTERN.search(str(block[4])):
            continue
        if (
            len(text) < 120
            or _horizontal_overlap(rect, scope) < 0.35
            or rect.width < scope.width * 0.35
        ):
            continue
        prose_bottom = max(prose_bottom, rect.y1 + 5)

    boundary = max(earliest, prose_bottom)
    all_graphics = _graphic_rects(page)
    nearby_graphics = [
        rect
        for rect in all_graphics
        if rect.y0 >= boundary - 4 and rect.y0 < caption.y0 + 5
    ]
    if nearby_graphics:
        graphic_left = min(rect.x0 for rect in nearby_graphics)
        graphic_right = max(rect.x1 for rect in nearby_graphics)
        parallel_caption = any(
            candidate["number"] != figure["number"]
            and int(candidate.get("caption_confidence") or 0) >= 2
            and abs(candidate["caption_rect"].y0 - caption.y0) <= page_rect.height * 0.18
            and _horizontal_overlap(candidate["caption_rect"], scope) < 0.2
            for candidate in _caption_candidates(page, figure["page_index"])
        )
        if (
            graphic_right - graphic_left >= page_rect.width * 0.58
            and not parallel_caption
        ):
            # The caption text itself can be short even when its multi-panel
            # figure spans both columns. Expand to full page before rendering.
            scope = fitz.Rect(
                page_rect.x0 + 14,
                page_rect.y0,
                page_rect.x1 - 14,
                page_rect.y1,
            )
    graphics = []
    for rect in all_graphics:
        if rect.y0 < boundary - 4 or rect.y0 >= caption.y0 + 5:
            continue
        if _horizontal_overlap(rect, scope) < 0.15:
            continue
        figure_band = fitz.Rect(scope.x0, boundary - 4, scope.x1, caption.y0 + 5)
        clipped = rect & figure_band
        if not clipped.is_empty:
            graphics.append(clipped)

    if graphics:
        top = min(rect.y0 for rect in graphics) - 8
    else:
        # Vector-free or flattened PDFs still get a full-column/page crop.
        top = max(boundary, caption.y0 - min(340, page_rect.height * 0.46))

    top = max(boundary - 4, top)
    bottom = min(page_rect.y1 - 8, caption.y1 + 8)
    crop = fitz.Rect(scope.x0, top, scope.x1, bottom) & page_rect
    if crop.width < 170 or crop.height < 60:
        return None
    return crop


def _scan_figures(document: fitz.Document) -> list[dict]:
    figures = []
    for page_index in range(min(document.page_count, MAX_FIGURE_SCAN_PAGES)):
        page = document.load_page(page_index)
        for candidate in _caption_candidates(page, page_index):
            crop = _find_complete_figure_crop(page, candidate)
            if crop is None:
                continue
            candidate["crop"] = crop
            figures.append(candidate)
    # A results paragraph can start with “Figure N presents ...” on the page
    # before the actual figure. Keep it only as a fallback: whenever a formal
    # “Figure N.” / “Figure N:” caption exists, bind the figure number to that
    # caption and its page instead. This prevents rendering a prose paragraph
    # as if it were the image.
    best_by_number: dict[int, dict] = {}
    for figure in figures:
        number = int(figure.get("number") or 0)
        previous = best_by_number.get(number)
        rank = (
            int(figure.get("caption_confidence") or 0),
            -int(figure.get("page_index") or 0),
        )
        previous_rank = (
            int(previous.get("caption_confidence") or 0),
            -int(previous.get("page_index") or 0),
        ) if previous else (-1, 0)
        if previous is None or rank > previous_rank:
            best_by_number[number] = figure
    selected = sorted(
        best_by_number.values(),
        key=lambda value: (int(value.get("number") or 0), int(value.get("page_index") or 0)),
    )
    method_references = _method_figure_references(document)
    for figure in selected:
        number = int(figure.get("number") or 0)
        page = document.load_page(int(figure.get("page_index") or 0))
        figure["method_reference_score"] = method_references.get(number, 0)
        figure["structure_score"] = _figure_structure_score(page, figure)
    return selected


def _method_figure_references(document: fitz.Document) -> dict[int, int]:
    """Count method-context references to each figure in the paper body."""
    references: dict[int, int] = {}
    pattern = re.compile(r"(?:figure|fig\.?)\s*(\d+)", re.I)
    for page_index in range(min(document.page_count, MAX_FIGURE_SCAN_PAGES)):
        text = re.sub(r"\s+", " ", document.load_page(page_index).get_text("text"))
        folded = text.casefold()
        for match in pattern.finditer(text):
            start = max(0, match.start() - 180)
            end = min(len(text), match.end() + 180)
            context = folded[start:end]
            score = sum(1 for keyword in METHOD_CONTEXT_KEYWORDS if keyword in context)
            if score:
                number = int(match.group(1))
                references[number] = max(references.get(number, 0), min(score, 6))
    return references


def _rect_overlap_area(left: fitz.Rect, right: fitz.Rect) -> float:
    overlap = fitz.Rect(left) & fitz.Rect(right)
    return 0.0 if overlap.is_empty else overlap.width * overlap.height


def _figure_structure_score(page: fitz.Page, figure: dict) -> int:
    """Estimate whether a crop contains a labeled module-and-flow diagram."""
    crop = fitz.Rect(figure["crop"])
    caption = fitz.Rect(figure["caption_rect"])
    content = fitz.Rect(crop.x0, crop.y0, crop.x1, min(crop.y1, caption.y0 - 2))
    if content.is_empty:
        return 0

    short_labels = 0
    for block in _text_blocks(page):
        rect = fitz.Rect(block[:4])
        text = re.sub(r"\s+", " ", str(block[4])).strip()
        if not text or _rect_overlap_area(rect, content) < rect.width * rect.height * 0.55:
            continue
        if len(text) <= 72 and len(text.split()) <= 10:
            short_labels += 1

    boxes = 0
    connectors = 0
    try:
        for drawing in page.get_drawings():
            rect = fitz.Rect(drawing.get("rect", (0, 0, 0, 0)))
            if rect.is_empty or _rect_overlap_area(rect, content) < 4:
                continue
            for item in drawing.get("items") or []:
                kind = item[0] if item else ""
                if kind == "re":
                    boxes += 1
                elif kind in {"l", "c", "qu"}:
                    connectors += 1
    except Exception:
        pass

    raster_tiles = 0
    try:
        for info in page.get_image_info(xrefs=True):
            rect = fitz.Rect(info.get("bbox", (0, 0, 0, 0)))
            if not rect.is_empty and _rect_overlap_area(rect, content) >= 64:
                raster_tiles += 1
    except Exception:
        pass

    score = min(6, short_labels // 2) + min(6, boxes // 2) + min(5, connectors // 4)
    # Photo grids often contain many separate raster tiles but almost no boxes,
    # connectors, or extractable short module labels.
    if raster_tiles >= 4 and boxes < 2 and connectors < 4 and short_labels < 4:
        score -= 5
    return max(-5, min(score, 17))


def _architecture_score(figure: dict) -> int:
    caption = str(figure.get("caption") or "").casefold()
    score = sum(weight for keyword, weight in ARCHITECTURE_KEYWORDS.items() if keyword in caption)
    score -= sum(
        weight for keyword, weight in NON_ARCHITECTURE_KEYWORDS.items() if keyword in caption
    )
    # Earlier figures are more likely to be the paper's main method overview.
    score += max(0, 5 - int(figure.get("number") or 99))
    score += min(6, int(figure.get("method_reference_score") or 0))
    score += min(8, int(figure.get("structure_score") or 0))
    score += min(5, _caption_component_score(figure))
    return score


def _caption_component_score(figure: dict) -> int:
    caption = str(figure.get("caption") or "").casefold()
    return sum(1 for keyword in MODULE_CONTEXT_KEYWORDS if keyword in caption)


def _is_architecture_figure(figure: dict) -> bool:
    caption = str(figure.get("caption") or "").casefold()
    negative = sum(
        weight for keyword, weight in NON_ARCHITECTURE_KEYWORDS.items() if keyword in caption
    )
    explicit = any(keyword in caption for keyword in EXPLICIT_ARCHITECTURE_KEYWORDS)
    structural = int(figure.get("structure_score") or 0)
    referenced = int(figure.get("method_reference_score") or 0)
    components = _caption_component_score(figure)
    return (
        int(figure.get("caption_confidence") or 0) >= 2
        and any(keyword in caption for keyword in STRONG_ARCHITECTURE_KEYWORDS)
        and (explicit or structural >= 3 or referenced >= 3 or components >= 3)
        and (negative < 12 or explicit)
        and _architecture_score(figure) >= MIN_ARCHITECTURE_SCORE
    )


def _teaser_score(figure: dict) -> int:
    caption = str(figure.get("caption") or "").casefold()
    score = sum(weight for keyword, weight in TEASER_KEYWORDS.items() if keyword in caption)
    if int(figure.get("number") or 0) == 1:
        score += 7
    if int(figure.get("caption_confidence") or 0) >= 2:
        score += 5
    return score


def _select_teaser_and_architecture(figures: list[dict]) -> list[tuple[str, dict]]:
    if not figures:
        return []
    formal = [
        figure
        for figure in figures
        if int(figure.get("caption_confidence") or 0) >= 2
    ]
    pool = formal or figures
    architecture_candidates = [figure for figure in pool if _is_architecture_figure(figure)]
    if not architecture_candidates:
        return []
    architecture = max(
        architecture_candidates,
        key=lambda value: (
            _architecture_score(value),
            -int(value.get("number") or 99),
        ),
    )
    teaser_candidates = [figure for figure in pool if figure is not architecture]
    if not teaser_candidates:
        return []
    teaser = max(
        teaser_candidates,
        key=lambda value: (
            _teaser_score(value),
            -int(value.get("number") or 99),
        ),
    )
    return [("teaser", teaser), ("architecture", architecture)]


def _keyword_score(figure: dict, weights: dict[str, int]) -> int:
    caption = str(figure.get("caption") or "").casefold()
    return sum(weight for keyword, weight in weights.items() if keyword in caption)


def _select_deep_reading_figures(figures: list[dict], limit: int = 5) -> list[tuple[str, dict]]:
    """Select distinct figures that explain the idea and support its claims."""
    primary = _select_teaser_and_architecture(figures)
    selected = list(primary)
    used = {id(figure) for _, figure in selected}
    used_numbers = {int(figure.get("number") or 0) for _, figure in selected}

    categories = (
        ("result", RESULT_KEYWORDS),
        ("ablation", ABLATION_KEYWORDS),
        ("qualitative", QUALITATIVE_KEYWORDS),
    )
    for kind, weights in categories:
        candidates = [
            figure
            for figure in figures
            if id(figure) not in used
            and int(figure.get("number") or 0) not in used_numbers
        ]
        if not candidates:
            break
        candidate = max(
            candidates,
            key=lambda value: (
                _keyword_score(value, weights),
                -int(value.get("page_index") or 0),
            ),
        )
        if _keyword_score(candidate, weights) <= 0:
            continue
        selected.append((kind, candidate))
        used.add(id(candidate))
        used_numbers.add(int(candidate.get("number") or 0))
        if len(selected) >= limit:
            return selected[:limit]

    # If caption wording is unusual, fill the gallery with the earliest distinct
    # figures so readers still get a useful visual path through the paper.
    for figure in figures:
        if id(figure) in used or int(figure.get("number") or 0) in used_numbers:
            continue
        selected.append(("evidence", figure))
        used.add(id(figure))
        used_numbers.add(int(figure.get("number") or 0))
        if len(selected) >= limit:
            break
    return selected[:limit]


def _expand_crop_to_aspect(
    crop: fitz.Rect,
    page_rect: fitz.Rect,
    target_aspect: float,
) -> fitz.Rect:
    """Expand, never shrink, a figure crop toward a stable card aspect ratio."""
    bounds = fitz.Rect(
        page_rect.x0 + 4,
        page_rect.y0 + 4,
        page_rect.x1 - 4,
        page_rect.y1 - 4,
    )
    result = fitz.Rect(crop) & bounds
    if result.is_empty or target_aspect <= 0:
        return fitz.Rect(crop)

    if result.width / max(result.height, 1) > target_aspect:
        desired_height = min(bounds.height, result.width / target_aspect)
        center = (result.y0 + result.y1) / 2
        y0 = max(bounds.y0, min(center - desired_height / 2, bounds.y1 - desired_height))
        result = fitz.Rect(result.x0, y0, result.x1, y0 + desired_height)
    else:
        desired_width = min(bounds.width, result.height * target_aspect)
        center = (result.x0 + result.x1) / 2
        x0 = max(bounds.x0, min(center - desired_width / 2, bounds.x1 - desired_width))
        result = fitz.Rect(x0, result.y0, x0 + desired_width, result.y1)
    return result & bounds


def _render_figure(
    document: fitz.Document,
    figure: dict,
    output_path: Path,
    *,
    target_aspect: float | None = None,
) -> None:
    page = document.load_page(figure["page_index"])
    crop = fitz.Rect(figure["crop"])
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(2.0, 2.0),
        clip=crop,
        alpha=False,
    )
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    if target_aspect:
        # Preserve the verified figure/caption boundary. Expanding a narrow
        # single-column figure to a wide card can pull unrelated prose or a
        # neighboring figure from the second column into the image. Normalize
        # the presentation ratio with white padding instead of a larger PDF crop.
        current = image.width / max(image.height, 1)
        if current > target_aspect:
            canvas_size = (image.width, math.ceil(image.width / target_aspect))
        else:
            canvas_size = (math.ceil(image.height * target_aspect), image.height)
        if canvas_size != image.size:
            canvas = Image.new("RGB", canvas_size, "white")
            canvas.paste(
                image,
                ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2),
            )
            image = canvas
    if image.width > 1440:
        height = round(image.height * 1440 / image.width)
        image = image.resize((1440, height), Image.Resampling.LANCZOS)
    image.save(output_path, format="JPEG", quality=92, optimize=True)


def _image_label(kind: str, figure_number: int) -> str:
    names = {
        "teaser": "Teaser",
        "architecture": "网络 / 方法架构图",
        "result": "关键结果图",
        "ablation": "消融 / 机制分析图",
        "qualitative": "定性对比图",
        "evidence": "补充证据图",
    }
    return f"{names.get(kind, '论文图')} · Figure {figure_number}"


def prepare_paper_deep_images(paper: dict, limit: int = 5) -> list[dict]:
    """Extract 3-5 complete, captioned figures for the deep-reading document."""
    cache_id = _safe_cache_id(paper)
    pdf_url = _validated_pdf_url(paper)
    if not cache_id or not pdf_url:
        return []

    limit = max(2, min(int(limit), 5))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = CACHE_DIR / f"{cache_id}-deep-figures-v7.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            cached = []
            for item in manifest[:limit]:
                path = CACHE_DIR / str(item.get("filename") or "")
                if not path.exists():
                    cached = []
                    break
                cached.append({**item, "path": path})
            if len(cached) >= 2 and {item.get("kind") for item in cached} >= {
                "teaser",
                "architecture",
            }:
                return cached
        except (OSError, ValueError, TypeError):
            pass

    pdf_bytes = _download_pdf(pdf_url)
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if document.page_count == 0:
            return []
        selected = _select_deep_reading_figures(_scan_figures(document), limit=limit)
        if len(selected) < 2:
            return []
        results = []
        for index, (kind, figure) in enumerate(selected, start=1):
            filename = f"{cache_id}-deep-{index}-{kind}-v7.jpg"
            path = CACHE_DIR / filename
            _render_figure(
                document,
                figure,
                path,
                target_aspect=TEASER_ASPECT_RATIO if kind == "teaser" else None,
            )
            crop = figure["crop"]
            width = 720
            height = max(120, min(720, round(width * crop.height / max(crop.width, 1))))
            results.append(
                {
                    "path": path,
                    "filename": filename,
                    "kind": kind,
                    "figure_number": figure["number"],
                    "page_number": int(figure["page_index"]) + 1,
                    "label": _image_label(kind, figure["number"]),
                    "caption": figure["caption"],
                    "width": width,
                    "height": height,
                }
            )
        manifest_path.write_text(
            json.dumps(
                [{key: value for key, value in item.items() if key != "path"} for item in results],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return results
    finally:
        document.close()


def prepare_paper_images(paper: dict) -> list[dict]:
    """Extract a complete teaser and a distinct method/network figure with captions."""
    cache_id = _safe_cache_id(paper)
    pdf_url = _validated_pdf_url(paper)
    if not cache_id or not pdf_url:
        return []

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    teaser_path = CACHE_DIR / f"{cache_id}-teaser-v9.jpg"
    architecture_path = CACHE_DIR / f"{cache_id}-architecture-v9.jpg"
    manifest_path = CACHE_DIR / f"{cache_id}-figures-v9.json"
    if manifest_path.exists() and teaser_path.exists() and architecture_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            cached = []
            for item in manifest:
                path = teaser_path if item.get("kind") == "teaser" else architecture_path
                cached.append({**item, "path": path})
            if {item.get("kind") for item in cached} == {"teaser", "architecture"}:
                return cached
        except (OSError, ValueError, TypeError):
            pass

    pdf_bytes = _download_pdf(pdf_url)
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if document.page_count == 0:
            return []
        selected = _select_teaser_and_architecture(_scan_figures(document))
        if len(selected) != 2:
            return []
        results = []
        for kind, figure in selected:
            path = teaser_path if kind == "teaser" else architecture_path
            _render_figure(
                document,
                figure,
                path,
                target_aspect=TEASER_ASPECT_RATIO if kind == "teaser" else None,
            )
            figure_number = figure["number"]
            label = (
                f"Teaser · Figure {figure_number}"
                if kind == "teaser"
                else f"网络 / 方法架构图 · Figure {figure_number}"
            )
            results.append(
                {
                    "path": path,
                    "kind": kind,
                    "figure_number": figure_number,
                    "label": label,
                    "caption": figure["caption"],
                }
            )
        if len(results) == 2:
            manifest_path.write_text(
                json.dumps(
                    [{key: value for key, value in item.items() if key != "path"} for item in results],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        return results
    finally:
        document.close()
