import json

import paper_bilingual
from paper_bilingual import enrich_bilingual_fields, normalize_bilingual_fields


def test_normalize_bilingual_fields_preserves_existing_chinese_guide():
    result = normalize_bilingual_fields(
        {
            "summary_zh": "新的中文导读",
            "summary_en": "An aligned English reading guide.",
            "abstract_zh": "摘要的完整中文翻译。",
        },
        {"title": "Paper", "summary": "已有的详细中文导读"},
    )
    assert result["summary"] == "已有的详细中文导读"
    assert result["summary_en"] == "An aligned English reading guide."
    assert result["abstract_zh"] == "摘要的完整中文翻译。"


def test_bilingual_generation_uses_official_abstract_and_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(paper_bilingual, "CACHE_DIR", tmp_path)
    calls = []

    def fake_call(prompt, **kwargs):
        calls.append(prompt)
        return json.dumps(
            {
                "summary_zh": "忠实中文导读。",
                "summary_en": "A faithful English guide.",
                "abstract_zh": "官方摘要的完整中文翻译。",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(paper_bilingual, "call_glm", fake_call)
    paper = {"title": "Paper", "abstract": "Official English abstract."}
    first = enrich_bilingual_fields(paper)
    second = enrich_bilingual_fields(paper)

    assert first["abstract_zh"] == "官方摘要的完整中文翻译。"
    assert second["summary_en"] == "A faithful English guide."
    assert len(calls) == 1
    assert "Official English abstract." in calls[0]
