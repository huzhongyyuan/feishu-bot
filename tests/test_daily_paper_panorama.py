from datetime import datetime, timezone
from types import SimpleNamespace

import daily_paper


def _recent_paper(arxiv_id: str, title: str) -> dict:
    return {
        "id": arxiv_id,
        "title": title,
        "published": datetime.now(timezone.utc).isoformat(),
    }


def test_recent_candidates_issue_targeted_panorama_query(monkeypatch):
    queries = []

    def fake_query(params):
        queries.append(params["search_query"])
        if "panoramic camera" in params["search_query"]:
            return [_recent_paper("2608.00002", "An Omnidirectional Camera Paper")]
        return [_recent_paper("2608.00001", "A General Vision Paper")]

    monkeypatch.setattr(daily_paper, "_query_arxiv", fake_query)
    papers = daily_paper.get_recent_arxiv_candidates(
        topics=["全景相机", "全景视频"]
    )

    assert len(queries) == 3
    assert any('all:"DeepSeek"' in query for query in queries)
    assert any('all:"omnidirectional camera"' in query for query in queries)
    assert any("cat:cs.GR" in query for query in queries)
    assert all("cat:cs.MM" not in query for query in queries)
    assert {paper["id"] for paper in papers} == {"2608.00001", "2608.00002"}


def test_recent_candidates_skip_panorama_query_for_unrelated_topics(monkeypatch):
    queries = []

    def fake_query(params):
        queries.append(params["search_query"])
        return [_recent_paper("2608.00001", "A General Vision Paper")]

    monkeypatch.setattr(daily_paper, "_query_arxiv", fake_query)
    daily_paper.get_recent_arxiv_candidates(topics=["人体动作"])
    assert len(queries) == 2
    assert any('all:"DeepSeek"' in query for query in queries)


def test_rss_entry_is_normalized_and_detected_as_panorama():
    entry = SimpleNamespace(
        link="https://arxiv.org/abs/2608.12345",
        title=" OmniVideo: 360-Degree Video Generation ",
        summary=(
            "arXiv:2608.12345v1 Announce Type: new Abstract: "
            "We generate equirectangular panoramic video."
        ),
        author="Alice Example, Bob Example",
        published="Wed, 12 Aug 2026 00:00:00 -0400",
        updated="",
        tags=[{"term": "cs.CV"}],
    )
    paper = daily_paper._rss_entry_to_paper(entry)
    assert paper["id"] == "2608.12345"
    assert paper["authors"] == ["Alice Example", "Bob Example"]
    assert paper["abstract"] == "We generate equirectangular panoramic video."
    assert daily_paper._paper_mentions_panorama(paper) is True
