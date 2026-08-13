from feishu_docs import _summary_table_payload
import json
import urllib.parse

from paper_archive import _decode_paper, _paper_year


def test_summary_table_uses_append_index():
    payload = _summary_table_payload([{"title": "Paper"}], index=12)
    assert payload["index"] == 12
    assert len(payload["children_id"]) == 1


def test_summary_table_first_column_is_a_daily_library_record():
    payload = _summary_table_payload(
        [
            {
                "title": "Open Paper",
                "push_time": "2026-08-11",
                "venue": "SIGGRAPH 2026",
                "authors": ["Author A", "Author B"],
                "institutions": ["Lab A"],
                "paper_url": "https://arxiv.org/abs/2608.00001",
                "code_url": "https://github.com/org/open-paper",
            }
        ]
    )
    text_blocks = [
        block
        for block in payload["descendants"]
        if block.get("block_type") == 2
    ]
    header = str(text_blocks[0])
    record = urllib.parse.unquote(str(text_blocks[6]))
    assert "论文信息" in header
    assert "2026-08-11" in record
    assert "SIGGRAPH 2026" in record
    assert "Author A" in record
    assert "https://arxiv.org/abs/2608.00001" in record
    assert "https://github.com/org/open-paper" in record


def test_paper_year_prefers_push_date():
    assert _paper_year(
        {"push_time": "2026-08-05", "published": "2025-12-31T00:00:00Z"}
    ) == 2026


def test_paper_year_falls_back_to_published_date():
    assert _paper_year({"published": "2026-07-30T00:00:00Z"}) == 2026


def test_archive_decode_restores_deep_reading_and_official_pdf():
    paper = _decode_paper(
        {
            "title": "Paper",
            "arxiv_id": "",
            "pdf_url": "https://conference.org/paper.pdf",
            "authors": "[]",
            "institutions": "[]",
            "contributions_original": "[]",
            "categories": "[]",
            "contributions": "",
            "research_question": json.dumps({"text": "问题", "source": "PDF p.1"}),
            "background": json.dumps([{"text": "背景", "source": "PDF p.2"}]),
            "method_result_map": "[]",
            "key_results": "[]",
            "evidence_chain": "[]",
            "discussion_highlights": "[]",
            "limitations": "[]",
            "writing_notes": "[]",
        }
    )

    assert paper["pdf_url"] == "https://conference.org/paper.pdf"
    assert paper["research_question"]["text"] == "问题"
    assert paper["background"][0]["source"] == "PDF p.2"
