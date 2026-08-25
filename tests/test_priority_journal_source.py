import priority_journal_source


def test_priority_journal_source_uses_official_issn_and_exact_arxiv_match(monkeypatch):
    requested = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, **kwargs):
        requested.append(url)
        if "/1552-3098/" in url:
            return Response(
                {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.1109/TRO.2026.1234567",
                                "title": ["Learning Whole-Body Humanoid Robot Control"],
                                "container-title": ["IEEE Transactions on Robotics"],
                                "published-online": {"date-parts": [[2026, 8, 1]]},
                                "volume": "42",
                                "issue": "8",
                            }
                        ]
                    }
                }
            )
        return Response({"message": {"items": []}})

    def fake_post(url, **kwargs):
        return Response(
            [
                {
                    "title": "Learning Whole-Body Humanoid Robot Control",
                    "externalIds": {"ArXiv": "2608.12345"},
                }
            ]
        )

    monkeypatch.setattr(priority_journal_source.requests, "get", fake_get)
    monkeypatch.setattr(priority_journal_source.requests, "post", fake_post)
    monkeypatch.setattr(
        priority_journal_source,
        "_query_arxiv",
        lambda params: [
            {
                "id": "2608.12345",
                "title": "Learning Whole-Body Humanoid Robot Control",
                "paper_url": "https://arxiv.org/abs/2608.12345",
            }
        ],
    )

    papers = priority_journal_source.get_priority_journal_candidates(
        ["humanoid robot"], limit=3
    )

    assert [paper["id"] for paper in papers] == ["2608.12345"]
    assert papers[0]["venue"] == "IEEE T-RO 2026"
    assert papers[0]["journal_verified"] is True
    assert papers[0]["official_venue_url"] == (
        "https://doi.org/10.1109/TRO.2026.1234567"
    )
    assert any(url.endswith("/journals/1552-3098/works") for url in requested)
    assert any(url.endswith("/journals/2377-3766/works") for url in requested)
    assert any(url.endswith("/journals/0730-0301/works") for url in requested)
