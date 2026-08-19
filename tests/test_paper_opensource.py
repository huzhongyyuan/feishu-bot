import base64
import json

import paper_opensource


def _paper(**overrides):
    value = {
        "id": "2608.12345",
        "title": "Awesome Video Model: Reliable Long-Horizon Generation",
        "authors": ["A", "B", "C", "D", "E"],
        "paper_url": "https://arxiv.org/abs/2608.12345",
    }
    value.update(overrides)
    return value


def test_repo_url_is_normalized_to_project_root():
    assert paper_opensource._normalize_repo_url(
        "https://github.com/org/repo/tree/main/demo"
    ) == "https://github.com/org/repo"
    assert paper_opensource._normalize_repo_url(
        "https://gitlab.com/group/repo/-/blob/main/README.md"
    ) == "https://gitlab.com/group/repo"


def test_llm_confirms_official_open_source_link(monkeypatch):
    monkeypatch.setattr(
        paper_opensource,
        "call_glm",
        lambda *args, **kwargs: json.dumps(
            {
                "papers": [
                    {
                        "title": _paper()["title"],
                        "is_open_source": True,
                        "code_url": "https://github.com/org/awesome-video-model/tree/main",
                        "evidence": "论文官方页指向该仓库。",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    result = paper_opensource.llm_confirm_open_source_links([_paper()])
    assert result[_paper()["title"]]["code_url"] == "https://github.com/org/awesome-video-model"
    assert result[_paper()["title"]]["llm_open_source_verified"] is True


def test_filter_requires_llm_confirmation_before_repository_verification(monkeypatch):
    calls = []

    def confirm(papers):
        calls.append("llm")
        return {
            papers[0]["title"]: {
                "code_url": "https://github.com/org/repo",
                "llm_open_source_verified": True,
                "llm_open_source_evidence": "README 对应论文。",
            }
        }

    def enrich(paper):
        calls.append("api")
        assert paper["llm_open_source_verified"] is True
        return {**paper, "open_source_verified": True}

    monkeypatch.setattr(paper_opensource, "llm_confirm_open_source_links", confirm)
    monkeypatch.setattr(paper_opensource, "enrich_open_source_paper", enrich)
    result = paper_opensource.filter_open_source_large_team([_paper()])
    assert calls == ["llm", "api"]
    assert result[0]["open_source_verified"] is True


def test_filter_batches_large_candidate_sets_for_browser_llm(monkeypatch):
    papers = [_paper(title=f"Paper {index}") for index in range(18)]
    batch_sizes = []

    def confirm(batch):
        batch_sizes.append(len(batch))
        return {}

    monkeypatch.setattr(paper_opensource, "llm_confirm_open_source_links", confirm)

    assert paper_opensource.filter_open_source_large_team(papers) == []
    assert batch_sizes == [8, 8, 2]


def test_filter_prioritizes_candidates_with_code_signals(monkeypatch):
    plain = _paper(title="Plain Paper")
    signaled = _paper(
        title="Signaled Paper",
        code_url="https://github.com/org/signaled",
    )
    seen = []

    def confirm(batch):
        seen.extend(paper["title"] for paper in batch)
        return {}

    monkeypatch.setattr(paper_opensource, "llm_confirm_open_source_links", confirm)
    paper_opensource.filter_open_source_large_team([plain, signaled])
    assert seen[0] == "Signaled Paper"


def test_small_team_without_confirmed_code_is_rejected(monkeypatch):
    called = []
    monkeypatch.setattr(
        paper_opensource,
        "llm_confirm_open_source_links",
        lambda papers: called.append(papers) or {},
    )
    assert paper_opensource.filter_open_source_large_team(
        [_paper(authors=["A", "B"])]
    ) == []
    assert len(called) == 1
    assert called[0][0]["authors"] == ["A", "B"]


def test_small_team_from_top_university_can_pass(monkeypatch):
    paper = _paper(
        authors=["A", "B"],
        institutions=["Stanford University"],
    )
    monkeypatch.setattr(
        paper_opensource,
        "llm_confirm_open_source_links",
        lambda papers: {
            paper["title"]: {
                "code_url": "https://github.com/org/repo",
                "llm_open_source_verified": True,
                "llm_open_source_evidence": "官方项目页确认仓库。",
            }
        },
    )
    monkeypatch.setattr(
        paper_opensource,
        "enrich_open_source_paper",
        lambda value: {
            **value,
            "open_source_verified": True,
            "large_team_verified": True,
        },
    )
    result = paper_opensource.filter_open_source_large_team([paper])
    assert len(result) == 1


def test_major_company_gets_highest_institution_tier():
    result = paper_opensource.institution_impact(
        _paper(institutions=["NVIDIA Research", "Stanford University"])
    )
    assert result["institution_impact_tier"] == 3
    assert result["institution_impact_label"] == "大公司/头部研究机构"
    assert result["institution_impact_evidence"] == "nvidia"


def test_top_university_gets_academic_tier():
    result = paper_opensource.institution_impact(
        _paper(institutions=["Carnegie Mellon University"])
    )
    assert result["institution_impact_tier"] == 2
    assert result["institution_impact_label"] == "顶级高校/研究机构"


def test_inria_gets_academic_tier():
    result = paper_opensource.institution_impact(
        _paper(institutions=["INRIA, France", "CEA, France"])
    )
    assert result["institution_impact_tier"] == 2


def test_project_page_supplies_llm_code_signal(monkeypatch):
    monkeypatch.setattr(
        paper_opensource,
        "_urls_from_page",
        lambda url: ["https://github.com/hucebot/HUI360-Baselines"],
    )
    paper = _paper(
        summary="Project page: https://hucebot.github.io/hui360.",
    )
    assert paper_opensource._discover_llm_code_signals(paper) == [
        "https://github.com/hucebot/HUI360-Baselines"
    ]


def test_llm_signal_evidence_includes_readme(monkeypatch):
    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if url.endswith("/readme"):
            readme = "# HUI360 Baselines Paper arXiv:2608.11051"
            return Response(
                200,
                {
                    "encoding": "base64",
                    "content": base64.b64encode(readme.encode()).decode(),
                },
            )
        return Response(
            200,
            {
                "description": "Official HUI360 baselines",
                "homepage": "https://arxiv.org/abs/2608.11051",
            },
        )

    monkeypatch.setattr(paper_opensource.requests, "get", fake_get)
    evidence = paper_opensource._llm_signal_evidence(
        "https://github.com/hucebot/HUI360-Baselines"
    )
    assert evidence["description"] == "Official HUI360 baselines"
    assert "2608.11051" in evidence["readme_excerpt"]


def test_short_organization_name_does_not_match_inside_another_word():
    result = paper_opensource.institution_impact(
        _paper(institutions=["Committee for Computer Vision"])
    )
    assert result["institution_impact_tier"] == 1


def test_github_api_and_readme_must_match_paper(monkeypatch):
    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        if url.endswith("/readme"):
            readme = "# Awesome Video Model\nPaper: arXiv:2608.12345"
            return Response(
                200,
                {
                    "encoding": "base64",
                    "content": base64.b64encode(readme.encode()).decode(),
                },
            )
        return Response(
            200,
            {
                "private": False,
                "disabled": False,
                "archived": False,
                "name": "awesome-video-model",
                "full_name": "org/awesome-video-model",
                "description": "Official implementation",
                "homepage": "https://arxiv.org/abs/2608.12345",
                "html_url": "https://github.com/org/awesome-video-model",
                "stargazers_count": 42,
            },
        )

    monkeypatch.setattr(paper_opensource.requests, "get", fake_get)
    result = paper_opensource.verify_repository(
        "https://github.com/org/awesome-video-model", _paper()
    )
    assert result["code_url"] == "https://github.com/org/awesome-video-model"
    assert result["repo_stars"] == 42
