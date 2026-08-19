from pathlib import Path

import fitz

from paper_media import (
    _render_figure,
    _safe_cache_id,
    _scan_figures,
    _select_deep_reading_figures,
    _select_teaser_and_architecture,
    _validated_pdf_url,
)


def _build_two_figure_pdf() -> fitz.Document:
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_textbox(
        fitz.Rect(35, 30, 565, 85),
        "This introductory paragraph deliberately contains enough text to be "
        "recognized as prose before the complete teaser figure region begins. "
        "It should not appear inside the rendered figure crop.",
        fontsize=10,
    )
    page.draw_rect(fitz.Rect(40, 105, 285, 245), color=(0, 0, 0), fill=(0.9, 0.9, 1))
    page.draw_rect(fitz.Rect(315, 105, 560, 245), color=(0, 0, 0), fill=(1, 0.9, 0.9))
    page.insert_text((55, 130), "left teaser panel", fontsize=12)
    page.insert_text((330, 130), "right teaser panel", fontsize=12)
    page.insert_textbox(
        fitz.Rect(430, 150, 555, 220),
        "A deliberately long natural-language control instruction inside the "
        "figure must remain part of the figure and must never be mistaken for "
        "the prose paragraph that precedes it.",
        fontsize=6,
    )
    page.insert_textbox(
        fitz.Rect(35, 255, 565, 290),
        "Figure 1. Complete two-panel teaser showing input and final output.",
        fontsize=10,
    )
    page.insert_textbox(
        fitz.Rect(35, 315, 565, 370),
        "This method paragraph is intentionally long enough to form a reliable "
        "layout boundary before the architecture diagram and must stay outside "
        "the extracted architecture image.",
        fontsize=10,
    )
    for index in range(4):
        left = 55 + index * 125
        page.draw_rect(
            fitz.Rect(left, 410, left + 85, 500),
            color=(0, 0, 0),
            fill=(0.9, 1, 0.9),
        )
        if index < 3:
            page.draw_line((left + 85, 455), (left + 125, 455), color=(0, 0, 0))
    page.insert_textbox(
        fitz.Rect(35, 520, 565, 560),
        "Figure 2. Overview of our complete network architecture and training pipeline.",
        fontsize=10,
    )
    return document


def test_extracts_two_complete_distinct_figures_with_captions(tmp_path: Path):
    source = _build_two_figure_pdf()
    pdf_bytes = source.tobytes()
    source.close()
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        figures = _scan_figures(document)
        selected = _select_teaser_and_architecture(figures)
        assert [kind for kind, _ in selected] == ["teaser", "architecture"]
        assert selected[0][1]["number"] == 1
        assert selected[1][1]["number"] == 2
        assert "network architecture" in selected[1][1]["caption"]
        assert all(
            figure["crop"].contains(figure["caption_rect"])
            for figure in figures
        )
        # Both drawings span almost the full page; a partial sub-image crop would
        # be around 245 pt wide, while the complete crop remains over 500 pt.
        assert selected[0][1]["crop"].width > 500
        assert selected[1][1]["crop"].width > 500
        assert selected[0][1]["crop"].y0 <= 105

        teaser_path = tmp_path / "teaser.jpg"
        architecture_path = tmp_path / "architecture.jpg"
        _render_figure(document, selected[0][1], teaser_path)
        _render_figure(document, selected[1][1], architecture_path)
        assert teaser_path.stat().st_size > 1000
        assert architecture_path.stat().st_size > 1000
    finally:
        document.close()


def test_official_cvpr_pdf_uses_stable_hashed_cache_id():
    paper = {
        "title": "Official Conference Paper",
        "paper_url": "https://openaccess.thecvf.com/content/CVPR2026/html/paper.html",
        "pdf_url": "https://openaccess.thecvf.com/content/CVPR2026/papers/paper.pdf",
    }
    assert _safe_cache_id(paper).startswith("official-")
    assert _safe_cache_id(paper) == _safe_cache_id(dict(paper))
    assert _validated_pdf_url(paper) == paper["pdf_url"]


def test_untrusted_pdf_host_is_rejected():
    paper = {"title": "Unsafe", "pdf_url": "https://127.0.0.1/private.pdf"}
    assert _validated_pdf_url(paper) == ""


def test_method_diagram_beats_qualitative_or_analysis_figure():
    figures = [
        {"number": 1, "page_index": 0, "caption_confidence": 2, "caption": "Figure 1. Teaser."},
        {
            "number": 3,
            "page_index": 2,
            "caption_confidence": 2,
            "caption": "Figure 3. PCA analysis motivating KV-cache compression.",
        },
        {
            "number": 5,
            "page_index": 4,
            "caption_confidence": 2,
            "structure_score": 4,
            "caption": "Figure 5. Temporal correspondence for KV compression.",
        },
        {
            "number": 7,
            "page_index": 6,
            "caption_confidence": 2,
            "caption": "Figure 7. Qualitative comparison of our method.",
        },
    ]
    selected = _select_teaser_and_architecture(figures)
    assert selected[1][1]["number"] == 5


def test_deep_gallery_selects_claim_supporting_figures():
    figures = [
        {"number": 1, "page_index": 0, "caption_confidence": 2, "caption": "Figure 1. Teaser."},
        {"number": 2, "page_index": 2, "caption_confidence": 2, "caption": "Figure 2. Our network architecture."},
        {"number": 3, "page_index": 5, "caption_confidence": 2, "caption": "Figure 3. Quantitative comparison results."},
        {"number": 4, "page_index": 6, "caption_confidence": 2, "caption": "Figure 4. Ablation study on each component."},
        {"number": 5, "page_index": 7, "caption_confidence": 2, "caption": "Figure 5. Qualitative visual comparison."},
    ]

    selected = _select_deep_reading_figures(figures)

    assert [kind for kind, _ in selected] == [
        "teaser",
        "architecture",
        "result",
        "ablation",
        "qualitative",
    ]
    assert len({figure["number"] for _, figure in selected}) == 5


def test_prose_figure_reference_is_not_selected_as_architecture():
    figures = [
        {
            "number": 1,
            "page_index": 2,
            "caption_confidence": 2,
            "caption": "Figure 1: Overview of our multimodal model and generation pipeline.",
        },
        {
            "number": 2,
            "page_index": 9,
            "caption_confidence": 2,
            "caption": "Figure 2: Qualitative results with facial expressions and gestures.",
        },
        {
            "number": 3,
            "page_index": 8,
            "caption_confidence": 1,
            "caption": (
                "Figure 3 presents frames from two dialogue-generated video responses "
                "whose model-generated VTPs contain explicit emotion descriptions."
            ),
        },
    ]

    selected = _select_teaser_and_architecture(figures)

    assert [(kind, figure["number"]) for kind, figure in selected] == [
        ("teaser", 2),
        ("architecture", 1),
    ]


def test_two_unpunctuated_captions_can_supply_strong_architecture_diagram():
    figures = [
        {
            "number": 1,
            "page_index": 1,
            "caption_confidence": 1,
            "structure_score": 7,
            "method_reference_score": 3,
            "caption": "Figure 1 Two examples of time-aligned world events.",
        },
        {
            "number": 2,
            "page_index": 2,
            "caption_confidence": 1,
            "structure_score": 11,
            "method_reference_score": 2,
            "caption": (
                "Figure 2 The world context is tokenized before streaming. "
                "Language, audio, and video inputs and outputs share a causal "
                "timeline coordinated by block-causal attention."
            ),
        },
    ]

    selected = _select_teaser_and_architecture(figures)

    assert [(kind, figure["number"]) for kind, figure in selected] == [
        ("teaser", 1),
        ("architecture", 2),
    ]


def test_two_figure_prose_reference_still_cannot_fill_architecture_slot():
    figures = [
        {
            "number": 1,
            "page_index": 0,
            "caption_confidence": 2,
            "structure_score": 0,
            "caption": "Figure 1. Examples from the benchmark.",
        },
        {
            "number": 2,
            "page_index": 4,
            "caption_confidence": 1,
            "structure_score": 2,
            "method_reference_score": 1,
            "caption": (
                "Figure 2 presents frames from generated clips with emotion "
                "descriptions and smiling dynamics."
            ),
        },
    ]

    assert _select_teaser_and_architecture(figures) == []


def test_unpunctuated_training_pipeline_is_accepted_without_replacing_figure_one_teaser():
    figures = [
        {
            "number": 1,
            "page_index": 0,
            "caption_confidence": 1,
            "structure_score": 9,
            "caption": "Figure 1 We propose an interactive video world model.",
        },
        {
            "number": 2,
            "page_index": 3,
            "caption_confidence": 1,
            "structure_score": 15,
            "method_reference_score": 4,
            "caption": (
                "Figure 2 Training pipeline of the model. The frozen base model "
                "generates clips and the training process conditions the DiT."
            ),
        },
        {
            "number": 5,
            "page_index": 7,
            "caption_confidence": 1,
            "structure_score": 10,
            "caption": "Figure 5 Qualitative comparison with baseline methods.",
        },
    ]

    selected = _select_teaser_and_architecture(figures)

    assert [(kind, figure["number"]) for kind, figure in selected] == [
        ("teaser", 1),
        ("architecture", 2),
    ]


def test_performance_graph_cannot_fill_architecture_slot():
    figures = [
        {
            "number": 1,
            "page_index": 0,
            "caption_confidence": 2,
            "structure_score": 0,
            "caption": "Figure 1. Examples from our panoramic benchmark.",
        },
        {
            "number": 4,
            "page_index": 3,
            "caption_confidence": 2,
            "structure_score": 2,
            "method_reference_score": 3,
            "caption": "Figure 4. Success rate graph across tasks and models.",
        },
    ]

    assert _select_teaser_and_architecture(figures) == []


def test_pipe_delimited_security_paper_uses_workflow_teaser_and_runtime_adapter():
    figures = [
        {
            "number": 1,
            "page_index": 0,
            "caption_confidence": 2,
            "structure_score": 0,
            "caption": "Figure 1 | Assessment workflow for the agent harness.",
        },
        {
            "number": 3,
            "page_index": 4,
            "caption_confidence": 2,
            "structure_score": 0,
            "caption": "Figure 3 | Runtime adapter for the agent harness.",
        },
        {
            "number": 6,
            "page_index": 8,
            "caption_confidence": 2,
            "structure_score": 10,
            "caption": "Figure 6 | Overall attack results and success-rate chart.",
        },
    ]

    selected = _select_teaser_and_architecture(figures)

    assert [(kind, figure["number"]) for kind, figure in selected] == [
        ("teaser", 1),
        ("architecture", 3),
    ]
