"""Generic first-party GitHub/PDF technical-report discovery adapter."""

from __future__ import annotations

from typing import Callable

import requests


USER_AGENT = "HumanGroupBot/1.0 official report verifier"

DEFAULT_REPORT_SPECS = [
    {
        "id": "official-deepseek-cordis-2026-08-13",
        "title": "A Programming Paradigm for Spatiotemporal Composability",
        "authors": ["Yifan Shi", "Wei Zhang", "Tianyi Cui"],
        "institutions": ["Peking University", "DeepSeek-AI"],
        "published": "2026-08-13T00:00:00+00:00",
        "categories": ["Agent Systems", "Programming Languages"],
        "source": "DeepSeek-AI 官方 GitHub 技术报告",
        "lab_page_url": "https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/master/README.md",
        "report_page_url": "https://raw.githubusercontent.com/cordiverse/paper/main/README.md",
        "required_report_link": "https://github.com/cordiverse/paper",
        "paper_url": "https://github.com/cordiverse/paper",
        "pdf_url": "https://raw.githubusercontent.com/cordiverse/paper/main/paper.pdf",
        "project_url": "https://github.com/deepseek-ai/deepseek-harness",
        "code_url": "https://github.com/deepseek-ai/deepseek-harness",
        "abstract": (
            "Modern software—from plugin systems to self-evolving agent harnesses—"
            "increasingly requires dynamic composition, yet its formal foundations "
            "remain underdeveloped. We identify two orthogonal dimensions of the "
            "problem: temporal composability, the ability to completely revert a "
            "component's side effects upon removal, and spatial composability, the "
            "ability to declare and reactively manage inter-component dependencies. "
            "We address the two dimensions by lifting classical effect and coeffect "
            "concepts to runtime mechanisms. In particular, we formalize revertible "
            "effects, in which every context transformation carries an inverse that "
            "the runtime tracks. We formalize reactive coeffects, in which each change "
            "of the context notifies a component against its coeffect specification. "
            "We unify the effect context and the coeffect context into a single context "
            "type, which constitutes a programming paradigm. After that, we combine "
            "these mechanisms into the notion of a component and give a calculus of "
            "dynamic composition, whose metatheory carries spatiotemporal composability "
            "from a single component to a whole system of interleaved components. We "
            "implement these ideas in Cordis, a meta-framework of spatiotemporal "
            "composability that provides a core library with effect tracking and "
            "coeffect resolution, as well as a declarative component loader with "
            "configuration reconciliation and hot module replacement."
        ),
    }
]


def discover_official_reports(
    specs: list[dict] | None = None,
    get: Callable[..., requests.Response] = requests.get,
) -> list[dict]:
    """Verify report provenance through a first-party lab page and report page.

    New labs can be added as data-only specs; the adapter does not assume arXiv or
    a particular repository owner.
    """
    reports = []
    for spec in specs or DEFAULT_REPORT_SPECS:
        try:
            lab_response = get(
                spec["lab_page_url"],
                timeout=20,
                headers={"User-Agent": USER_AGENT},
            )
            lab_response.raise_for_status()
            report_response = get(
                spec["report_page_url"],
                timeout=20,
                headers={"User-Agent": USER_AGENT},
            )
            report_response.raise_for_status()
        except (KeyError, requests.RequestException) as exc:
            print(f"官方技术报告读取失败: {spec.get('title', 'unknown')}: {exc}", flush=True)
            continue
        title = str(spec.get("title") or "").strip()
        report_link = str(spec.get("required_report_link") or spec.get("paper_url") or "")
        if not title or title not in report_response.text or report_link not in lab_response.text:
            print(f"官方技术报告交叉链接核验失败: {title or 'unknown'}", flush=True)
            continue
        abstract = str(spec.get("abstract") or "").strip()
        report = {
            key: value
            for key, value in spec.items()
            if key not in {"lab_page_url", "report_page_url", "required_report_link"}
        }
        report.update(
            {
                "summary": abstract,
                "url": report.get("paper_url", ""),
                "updated": report.get("published", ""),
                "verified_source": True,
                "official_github_report": True,
            }
        )
        reports.append(report)
    return reports
