import daily_paper
from official_report_source import discover_official_reports


class _Response:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_deepseek_harness_official_report_is_verified_from_cross_links(monkeypatch):
    def fake_get(url, **kwargs):
        if "deepseek-harness" in url:
            return _Response(
                "A Programming Paradigm for Spatiotemporal Composability "
                "https://github.com/cordiverse/paper"
            )
        return _Response("# A Programming Paradigm for Spatiotemporal Composability")

    monkeypatch.setattr(daily_paper.requests, "get", fake_get)

    report = daily_paper.get_official_tech_reports()[0]

    assert report["institutions"] == ["Peking University", "DeepSeek-AI"]
    assert report["code_url"] == "https://github.com/deepseek-ai/deepseek-harness"
    assert report["official_github_report"] is True


def test_generic_official_report_adapter_accepts_data_only_spec():
    spec = {
        "id": "lab-report",
        "title": "A Verified Lab Report",
        "authors": ["A"],
        "institutions": ["Lab"],
        "published": "2026-08-18T00:00:00+00:00",
        "source": "Lab official report",
        "lab_page_url": "https://lab.example/readme",
        "report_page_url": "https://report.example/readme",
        "required_report_link": "https://report.example/project",
        "paper_url": "https://report.example/project",
        "pdf_url": "https://report.example/paper.pdf",
        "code_url": "https://github.com/lab/project",
        "abstract": "Verified abstract.",
    }

    def fake_get(url, **kwargs):
        if "lab.example" in url:
            return _Response("https://report.example/project")
        return _Response("# A Verified Lab Report")

    report = discover_official_reports([spec], get=fake_get)[0]
    assert report["verified_source"] is True
    assert report["code_url"] == "https://github.com/lab/project"
