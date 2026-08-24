import tpami_source


def test_tpami_source_requires_official_record_and_exact_arxiv_title(monkeypatch):
    requested = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1109/TPAMI.2025.3646016",
                            "title": ["DSwinIR: Rethinking Window-Based Attention for Image Restoration"],
                            "container-title": [tpami_source.TPAMI_NAME],
                            "published-print": {"date-parts": [[2026, 4]]},
                            "volume": "48",
                            "issue": "4",
                            "page": "4350-4366",
                        }
                    ]
                }
            }

    def fake_get(url, **kwargs):
        requested["url"] = url
        return Response()

    monkeypatch.setattr(tpami_source.requests, "get", fake_get)
    monkeypatch.setattr(
        tpami_source,
        "_query_arxiv",
        lambda params: [
            {
                "id": "2504.04869",
                "title": "DSwinIR: Rethinking Window-based Attention for Image Restoration",
                "paper_url": "https://arxiv.org/abs/2504.04869",
            }
        ],
    )
    papers = tpami_source.get_tpami_candidates(["图像"], limit=2)
    assert [paper["id"] for paper in papers] == ["2504.04869"]
    assert papers[0]["venue"] == "IEEE TPAMI 2026"
    assert papers[0]["journal_verified"] is True
    assert papers[0]["official_venue_url"] == "https://doi.org/10.1109/TPAMI.2025.3646016"
    assert papers[0]["journal_volume"] == "48"
    assert requested["url"].endswith("/journals/0162-8828/works")
