import json

import paper_db


def test_save_paper_persists_deep_reading(monkeypatch, tmp_path):
    monkeypatch.setattr(paper_db, "DB_PATH", str(tmp_path / "papers.db"))
    paper_db.save_paper(
        {
            "title": "Deep Reading Paper",
            "summary_en": "English guide.",
            "abstract_zh": "中文摘要。",
            "bilingual_source": "official_abstract",
            "pdf_url": "https://conference.org/paper.pdf",
            "official_venue_url": "https://conference.org/paper",
            "research_question": {"text": "核心问题", "source": "PDF p.1"},
            "background": [{"text": "研究背景", "source": "PDF p.2"}],
            "method_result_map": [
                {"method": "方法模块", "result": "实验结果", "source": "Table 1"}
            ],
            "deep_reading_source": "official_pdf",
            "core_insights": [{"finding": "关键结论", "source": "Table 1"}],
            "figure_insights": [{"figure_number": 2, "what_it_shows": "方法流程"}],
            "reading_guide": [{"text": "先看图二", "source": "编辑解读"}],
        }
    )

    with paper_db.get_conn() as connection:
        row = connection.execute(
            """
            SELECT pdf_url, official_venue_url, research_question,
                   background, method_result_map, deep_reading_source,
                   core_insights, figure_insights, reading_guide,
                   summary_en, abstract_zh, bilingual_source
            FROM papers WHERE title=?
            """,
            ("Deep Reading Paper",),
        ).fetchone()

    assert row[0] == "https://conference.org/paper.pdf"
    assert row[1] == "https://conference.org/paper"
    assert json.loads(row[2])["text"] == "核心问题"
    assert json.loads(row[3])[0]["source"] == "PDF p.2"
    assert json.loads(row[4])[0]["result"] == "实验结果"
    assert row[5] == "official_pdf"
    assert json.loads(row[6])[0]["finding"] == "关键结论"
    assert json.loads(row[7])[0]["figure_number"] == 2
    assert json.loads(row[8])[0]["text"] == "先看图二"
    assert row[9] == "English guide."
    assert row[10] == "中文摘要。"
    assert row[11] == "official_abstract"
