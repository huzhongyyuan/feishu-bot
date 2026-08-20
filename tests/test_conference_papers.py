import json

import daily_paper
import conference_papers
from conference_papers import SOURCES, enrich_conference_pdf, parse_official_list


def test_parse_cvpr_official_list():
    html = '<dt class="ptitle"><br><a href="html/paper.html">World Model Paper</a></dt>'
    papers = parse_official_list("cvpr", html, "https://cvpr.test/list")
    assert papers == [
        {
            "title": "World Model Paper",
            "official_url": "https://cvpr.test/html/paper.html",
        }
    ]


def test_parse_eccv_only_keeps_official_2026_entries():
    html = (
        '<dt class="ptitle"><br><a href=papers/eccv_2026/html/1.php>'
        'Motion Generation</a></dt>'
        '<dt class="ptitle"><br><a href=papers/eccv_2024/html/2.php>'
        'Old Motion Paper</a></dt>'
        '<dt class="ptitle"><br><a href=other.html>Other</a></dt>'
    )
    papers = parse_official_list("eccv", html, "https://www.ecva.net/papers.php")
    assert len(papers) == 1
    assert papers[0]["title"] == "Motion Generation"


def test_active_sources_cover_requested_2026_venues_without_eccv_2024():
    venues = {source["venue"] for source in SOURCES}
    assert {"CVPR 2026", "ECCV 2026", "ICML 2026"} <= venues
    assert "ECCV 2024" not in venues


def test_siggraph_asia_requires_explicit_acceptance_claim(monkeypatch):
    accepted = type(
        "Entry",
        (),
        {
            "id": "https://arxiv.org/abs/2608.12345v1",
            "title": "A World Model for Video Generation",
            "summary": "A world model for controllable video generation.",
            "arxiv_comment": "Accepted to SIGGRAPH Asia 2026 Technical Papers",
            "published": "2026-08-10T00:00:00Z",
            "updated": "2026-08-10T00:00:00Z",
            "authors": [{"name": "A"}],
            "tags": [{"term": "cs.CV"}],
        },
    )()
    submitted = type(
        "Entry",
        (),
        {
            "id": "https://arxiv.org/abs/2608.54321v1",
            "title": "Submitted Video Paper",
            "summary": "A video model.",
            "arxiv_comment": "Submitted to SIGGRAPH Asia 2026",
            "published": "2026-08-10T00:00:00Z",
            "updated": "2026-08-10T00:00:00Z",
            "authors": [{"name": "B"}],
            "tags": [{"term": "cs.CV"}],
        },
    )()
    response = type("Response", (), {"content": b"feed", "raise_for_status": lambda self: None})()
    monkeypatch.setattr(conference_papers.requests, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(
        conference_papers.feedparser,
        "parse",
        lambda value: type("Feed", (), {"entries": [accepted, submitted]})(),
    )

    papers = conference_papers._siggraph_asia_candidates(["世界模型"], set())
    assert [paper["id"] for paper in papers] == ["2608.12345"]
    assert papers[0]["venue"] == "SIGGRAPH Asia 2026"
    assert papers[0]["conference_verified"] is False


def test_panorama_topics_expand_to_english_conference_keywords():
    keywords = conference_papers._keywords(["全景相机", "全景视频"])
    assert "omnidirectional camera" in keywords
    assert "equirectangular video" in keywords
    assert "360-degree video" in keywords


def test_core_topics_expand_to_targeted_conference_keywords():
    keywords = conference_papers._keywords(
        ["数字人", "Motion Generation", "具身智能", "世界模型", "视频生成"]
    )
    assert "digital human" in keywords
    assert "motion generation" in keywords
    assert "vision-language-action" in keywords
    assert "world model" in keywords
    assert "video generation" in keywords


def test_parse_icml_excludes_position_papers():
    html = (
        '<a href="/virtual/2026/poster/1">Video Generation</a>'
        '<a href="/virtual/2026/poster/2">Position: A Claim</a>'
    )
    papers = parse_official_list("icml", html, "https://icml.cc")
    assert [paper["title"] for paper in papers] == ["Video Generation"]


def test_analysis_preserves_verified_conference_metadata(monkeypatch):
    payload = {
        "papers": [
            {
                "title": "Conference Paper",
                "summary": "总结",
                "main_method": "方法",
                "contributions": ["贡献"],
                "score": 9,
                "keep": True,
            }
        ]
    }
    monkeypatch.setattr(
        daily_paper,
        "call_glm",
        lambda *args, **kwargs: json.dumps(payload, ensure_ascii=False),
    )
    result = daily_paper.analyze_papers_batch(
        [
            {
                "title": "Conference Paper",
                "summary": "Official abstract",
                "abstract": "Official abstract",
                "paper_url": "https://official.test/paper",
                "source": "CVPR 2026 官方录用论文",
                "venue": "CVPR 2026",
                "conference_verified": True,
                "official_venue_url": "https://official.test/list",
            }
        ]
    )
    assert result[0]["venue"] == "CVPR 2026"
    assert result[0]["conference_verified"] is True
    assert result[0]["paper_url"] == "https://official.test/paper"


def test_icml_paper_is_enriched_with_exact_arxiv_match(monkeypatch):
    class Entry:
        id = "https://arxiv.org/abs/2602.01801v2"
        title = "Fast Autoregressive Video Diffusion and World Models with Temporal Cache Compression and Sparse Attention"
        published = "2026-02-02T08:31:21Z"
        updated = "2026-06-12T08:53:35Z"
        authors = [{"name": "Dvir Samuel"}]
        tags = [{"term": "cs.CV"}]

    monkeypatch.setattr(conference_papers, "_arxiv_entry_for_title", lambda title: Entry())
    result = enrich_conference_pdf(
        {
            "title": "FAST-AR: Fast Autoregressive Video Diffusion and World Models with Temporal Cache Compression and Sparse Attention",
            "venue": "ICML 2026",
            "paper_url": "https://icml.cc/virtual/2026/poster/63654",
            "pdf_url": "",
            "official_venue_url": "https://icml.cc/virtual/2026/papers.html",
        }
    )
    assert result["id"] == "2602.01801"
    assert result["paper_url"] == "https://arxiv.org/abs/2602.01801"
    assert result["pdf_url"] == "https://arxiv.org/pdf/2602.01801"
    assert result["official_venue_url"] == "https://icml.cc/virtual/2026/papers.html"
