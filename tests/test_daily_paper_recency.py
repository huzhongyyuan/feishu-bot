from datetime import datetime, timedelta, timezone

import daily_paper


def test_recent_arxiv_enrichment_failure_is_non_fatal(monkeypatch):
    import source_health

    sleeps = []
    monkeypatch.setattr(
        source_health,
        "track_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("source returned no candidates")
        ),
    )
    monkeypatch.setattr(daily_paper.time, "sleep", sleeps.append)
    assert daily_paper.get_tracked_recent_candidates(["世界模型"]) == []
    assert sleeps == [120]


def test_recent_arxiv_enrichment_retries_once_after_two_minutes(monkeypatch):
    import source_health

    calls = []
    sleeps = []

    def fake_track(*args, **kwargs):
        calls.append(args[0])
        if len(calls) == 1:
            raise RuntimeError("429 Too Many Requests")
        return [{"id": "2608.12345", "title": "Recovered paper"}]

    monkeypatch.setattr(source_health, "track_source", fake_track)
    monkeypatch.setattr(daily_paper.time, "sleep", sleeps.append)
    result = daily_paper.get_tracked_recent_candidates(["世界模型"])
    assert [paper["id"] for paper in result] == ["2608.12345"]
    assert calls == ["arxiv_recent", "arxiv_recent"]
    assert sleeps == [120]
from daily_paper import published_within_lookback, select_with_complete_images


def _paper(days_ago: int) -> dict:
    published = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {"published": published.isoformat()}


def test_recent_paper_is_allowed():
    assert published_within_lookback(_paper(29))


def test_old_paper_is_rejected():
    assert not published_within_lookback(_paper(31))


def test_missing_or_invalid_date_is_rejected():
    assert not published_within_lookback({})
    assert not published_within_lookback({"published": "not-a-date"})


def test_selection_skips_text_only_candidate(monkeypatch):
    def fake_images(paper):
        if paper["title"] == "No figures":
            return []
        return [
            {"kind": "teaser", "path": "/tmp/t.jpg"},
            {"kind": "architecture", "path": "/tmp/a.jpg"},
        ]

    monkeypatch.setattr("paper_media.prepare_paper_images", fake_images)
    primary = [{"title": "No figures", "score": 10}]
    analyzed = primary + [{"title": "Complete figures", "score": 9}]
    selected = select_with_complete_images(primary, analyzed, [], limit=1)
    assert [paper["title"] for paper in selected] == ["Complete figures"]


def test_influential_source_wins_when_quality_is_close():
    ordinary = {
        "score": 9.2,
        "institution_impact_tier": 1,
        "repo_stars": 0,
    }
    major_lab = {
        "score": 8.8,
        "institution_impact_tier": 3,
        "repo_stars": 0,
    }
    assert daily_paper._recommendation_priority(major_lab) > daily_paper._recommendation_priority(ordinary)


def test_institution_reputation_does_not_override_large_quality_gap():
    strong_ordinary = {
        "score": 9.7,
        "institution_impact_tier": 1,
        "repo_stars": 0,
    }
    weak_major_lab = {
        "score": 8.5,
        "institution_impact_tier": 3,
        "repo_stars": 0,
    }
    assert daily_paper._recommendation_priority(strong_ordinary) > daily_paper._recommendation_priority(weak_major_lab)


def test_push_time_selects_distinct_morning_and_evening_tracks():
    assert daily_paper.recommendation_track_for_time("08:00") == "major_impact"
    assert daily_paper.recommendation_track_for_time("20:00") == "focus_topics"


def test_evening_track_prefers_focus_paper():
    general = {
        "title": "General Language Model Optimization",
        "summary": "A compiler optimization for language models.",
        "score": 9.4,
        "institution_impact_tier": 3,
    }
    focus = {
        "title": "Streaming Human Motion Generation",
        "summary": "A real-time motion synthesis model.",
        "score": 8.8,
        "institution_impact_tier": 2,
    }
    assert daily_paper._track_priority(focus, "focus_topics") > daily_paper._track_priority(general, "focus_topics")
