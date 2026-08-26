import daily_paper


def _item(arxiv_id, upvotes, date="2026-08-26", comments=0):
    return {
        "paper": {
            "id": arxiv_id,
            "title": f"Paper {arxiv_id}",
            "summary": "Summary",
            "upvotes": upvotes,
            "submittedOnDailyAt": f"{date}T00:00:00.000Z",
        },
        "numComments": comments,
    }


def test_hf_daily_uses_official_api_and_ranks_newest_issue(monkeypatch):
    payload = [
        _item("2608.00001", 100, date="2026-08-25"),
        _item("2608.00002", 3, comments=1),
        _item("2608.00003", 30),
    ]
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    def fake_get(url, **kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr(daily_paper.requests, "get", fake_get)
    papers = daily_paper.get_hf_daily()

    assert calls == ["https://huggingface.co/api/daily_papers"]
    assert [paper["id"] for paper in papers] == ["2608.00003", "2608.00002"]
    assert [paper["hf_daily_rank"] for paper in papers] == [1, 2]
    assert all(paper["hf_daily_hot"] for paper in papers)


def test_hf_daily_falls_back_to_mirror(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [_item("2608.00004", 9)]

    def fake_get(url, **kwargs):
        calls.append(url)
        if "huggingface.co" in url:
            raise RuntimeError("official unavailable")
        return Response()

    monkeypatch.setattr(daily_paper.requests, "get", fake_get)
    papers = daily_paper.get_hf_daily()

    assert calls == list(daily_paper.HF_DAILY_URLS)
    assert [paper["id"] for paper in papers] == ["2608.00004"]


def test_verification_batch_reserves_slots_for_hf_hot_papers():
    ordinary = [
        {"id": f"ordinary-{index}", "title": f"Ordinary {index}"}
        for index in range(30)
    ]
    hot = [
        {
            "id": f"hot-{index}",
            "title": f"Hot {index}",
            "hf_daily_hot": True,
            "hf_upvotes": index,
        }
        for index in range(10)
    ]

    selected = daily_paper._priority_verification_candidates(
        ordinary + hot,
        limit=24,
        hf_reserve=8,
    )

    assert len(selected) == 24
    assert [paper["id"] for paper in selected[:8]] == [
        "hot-9", "hot-8", "hot-7", "hot-6",
        "hot-5", "hot-4", "hot-3", "hot-2",
    ]
