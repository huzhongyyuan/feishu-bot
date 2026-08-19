import json

import manual_recommend


def test_official_project_page_can_supply_repository_link(monkeypatch):
    class Response:
        text = '<a href="https://github.com/RobinWitch/EchoAvatar">Code</a>'

        def raise_for_status(self):
            return None

    monkeypatch.setattr(manual_recommend.requests, "get", lambda *args, **kwargs: Response())

    assert manual_recommend.official_source_links_repository(
        "Project Page: https://robinwitch.github.io/EchoAvatar-Page.",
        "https://github.com/RobinWitch/EchoAvatar",
        "https://robinwitch.github.io/EchoAvatar-Page/",
    )


def test_unofficial_project_page_cannot_supply_repository_link(monkeypatch):
    monkeypatch.setattr(
        manual_recommend.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )

    assert not manual_recommend.official_source_links_repository(
        "No project URL here",
        "https://github.com/unknown/repository",
        "https://unofficial.example/paper",
    )


def test_no_code_exception_survives_analysis_normalization(monkeypatch):
    source = {
        "id": "2607.15038",
        "title": "Video = World + Event Stream",
        "authors": [f"Author {index}" for index in range(6)],
        "paper_url": "https://arxiv.org/abs/2607.15038",
    }
    captured = {}

    monkeypatch.setattr(manual_recommend, "search_arxiv", lambda *args, **kwargs: [dict(source)])
    monkeypatch.setattr(manual_recommend, "enrich_papers_metadata", lambda papers: papers)
    monkeypatch.setattr(manual_recommend, "institution_impact", lambda paper: {})
    monkeypatch.setattr(
        manual_recommend,
        "analyze_papers_batch",
        lambda papers, topics=None: [
            {
                "id": papers[0]["id"],
                "title": papers[0]["title"],
                "authors": papers[0]["authors"],
                "paper_url": papers[0]["paper_url"],
            }
        ],
    )
    monkeypatch.setattr(
        manual_recommend,
        "prepare_paper_images",
        lambda paper: [{"kind": "teaser"}, {"kind": "architecture"}],
    )
    monkeypatch.setattr(manual_recommend, "enrich_deep_reading", lambda paper: paper)
    monkeypatch.setattr(manual_recommend, "enrich_bilingual_fields", lambda paper: paper)
    monkeypatch.setattr(
        manual_recommend,
        "archive_papers",
        lambda papers, topics=None: {"url": "https://example.test/paper-library"},
    )
    monkeypatch.setattr(
        manual_recommend,
        "send_message",
        lambda chat_id, payload: captured.update(json.loads(payload)),
    )
    monkeypatch.setattr(manual_recommend, "init_db", lambda: None)
    monkeypatch.setattr(manual_recommend, "save_paper", lambda paper: None)
    monkeypatch.setattr(manual_recommend, "save_delivery", lambda chat_id, title: None)

    result = manual_recommend.recommend_arxiv(
        "2607.15038",
        code_url="",
        project_url="https://wan-streamer.com/v0.3/index.html",
        chat_id="oc_test",
        allow_no_code=True,
    )

    assert result["sent"] is True
    assert captured["manual_no_code_exception"] is True
    assert captured["code_release_status"] == "official_code_not_released"
    assert captured["project_url"] == "https://wan-streamer.com/v0.3/index.html"
    assert captured["code_url"] == ""
