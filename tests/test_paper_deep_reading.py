import fitz

import paper_deep_reading
from paper_deep_reading import extract_numbered_pdf_text, normalize_deep_reading


def test_normalize_deep_reading_preserves_sources_and_editor_labels():
    result = normalize_deep_reading(
        {
            "summary": "研究问题、核心方案、关键结果与阅读价值。",
            "summary_en": "Problem, method, result, and reading value.",
            "abstract_zh": "官方英文摘要的完整中文翻译。",
            "research_question": {"text": "要解决什么？", "source": "PDF p.1"},
            "background": [{"text": "现有方法不足。", "source": "PDF p.2"}],
            "method_result_map": [
                {"method": "模块 A", "result": "指标提高", "source": "Table 1"}
            ],
            "writing_notes": [{"text": "论证结构清晰。"}],
            "core_insights": [
                {
                    "finding": "模块 A 是性能提升的关键。",
                    "why_it_matters": "说明收益来自结构设计。",
                    "transfer": "可优先验证关键模块。",
                    "source": "PDF p.6 / Table 1",
                }
            ],
            "figure_insights": [
                {
                    "figure_number": 2,
                    "what_it_shows": "完整方法流程。",
                    "why_it_matters": "揭示信息流。",
                    "reading_tip": "关注两条分支。",
                    "source": "PDF p.4 / Figure 2",
                }
            ],
            "reading_guide": [{"text": "先读 Figure 2，再读 Table 1。"}],
        },
        {"title": "Paper"},
    )

    assert result["research_question"] == {"text": "要解决什么？", "source": "PDF p.1"}
    assert result["summary_en"].startswith("Problem")
    assert result["abstract_zh"] == "官方英文摘要的完整中文翻译。"
    assert result["method_result_map"][0]["result"] == "指标提高"
    assert result["writing_notes"][0]["source"] == "编辑解读"
    assert result["core_insights"][0]["transfer"] == "可优先验证关键模块。"
    assert result["figure_insights"][0]["figure_number"] == 2
    assert result["reading_guide"][0]["source"] == "编辑解读"
    assert result["deep_reading_source"] == "official_pdf"


def test_extract_numbered_pdf_text_keeps_page_markers(monkeypatch):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Introduction and motivation for the research.")
    page = document.new_page()
    page.insert_text((72, 72), "Method and experimental result.")
    content = document.tobytes()
    document.close()
    monkeypatch.setattr(paper_deep_reading, "_download_pdf", lambda url: content)

    text, page_count = extract_numbered_pdf_text("https://example.com/paper.pdf")

    assert page_count == 2
    assert "[PDF p.1]" in text
    assert "[PDF p.2]" in text
    assert "Method and experimental result" in text
