import json

import alphaxiv_source


def test_extracts_unique_arxiv_ids_from_mcp_result():
    result = alphaxiv_source._extract_arxiv_ids(
        {
            "content": [
                {"text": "<paper id='2608.09143v2'>UniMoFlow</paper>"},
                {"text": "https://arxiv.org/abs/2608.10720 and 2608.09143"},
            ]
        }
    )
    assert result == ["2608.09143", "2608.10720"]


def test_same_day_empty_cache_does_not_query_again(tmp_path, monkeypatch):
    cache = tmp_path / "alphaxiv.json"
    cache.write_text(
        json.dumps({"date": "2026-08-13", "arxiv_ids": []}), encoding="utf-8"
    )
    monkeypatch.setattr(alphaxiv_source, "CACHE_PATH", cache)
    assert alphaxiv_source._load_cache("2026-08-13") == []
    assert alphaxiv_source._load_cache("2026-08-14") is None


def test_candidates_resolve_through_arxiv_and_keep_rank(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHAXIV_API_KEY", "secret")
    monkeypatch.setattr(alphaxiv_source, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(
        alphaxiv_source.AlphaXivMCPClient,
        "discover",
        lambda self, topics, published_after: {
            "content": [{"text": "2608.10720 then 2608.09143"}]
        },
    )
    monkeypatch.setattr(
        alphaxiv_source,
        "_query_arxiv",
        lambda params: [
            {"id": "2608.09143", "title": "UniMoFlow"},
            {"id": "2608.10720", "title": "Ex-Omni-2D"},
        ],
    )

    papers = alphaxiv_source.get_alphaxiv_candidates(["motion generation"])

    assert [paper["id"] for paper in papers] == ["2608.10720", "2608.09143"]
    assert all(paper["discovery_source"] == "alphaXiv" for paper in papers)
