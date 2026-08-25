import science_robotics_source


def test_science_robotics_source_matches_official_zest_record(monkeypatch):
    requested = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1126/scirobotics.aec7695",
                            "title": [
                                "ZEST: Zero-shot embodied skill transfer for athletic robot control"
                            ],
                            "container-title": [science_robotics_source.JOURNAL_NAME],
                            "published-online": {"date-parts": [[2026, 8, 12]]},
                            "volume": "11",
                            "issue": "117",
                        }
                    ]
                }
            }

    def fake_get(url, **kwargs):
        requested["url"] = url
        return Response()

    monkeypatch.setattr(science_robotics_source.requests, "get", fake_get)
    monkeypatch.setattr(
        science_robotics_source,
        "_query_arxiv",
        lambda params: [
            {
                "id": "2602.00401",
                "title": "ZEST: Zero-shot Embodied Skill Transfer for Athletic Robot Control",
                "paper_url": "https://arxiv.org/abs/2602.00401",
            }
        ],
    )
    papers = science_robotics_source.get_science_robotics_candidates(
        ["embodied intelligence"], limit=2
    )
    assert [paper["id"] for paper in papers] == ["2602.00401"]
    assert papers[0]["venue"] == "Science Robotics 2026"
    assert papers[0]["journal_verified"] is True
    assert papers[0]["official_venue_url"] == (
        "https://doi.org/10.1126/scirobotics.aec7695"
    )
    assert requested["url"].endswith("/journals/2470-9476/works")
