from __future__ import annotations

import json
import base64
import os
import re
import time
import urllib.parse
from pathlib import Path

import fitz
import requests

from glm_client import call_glm
from paper_media import _download_pdf, _validated_pdf_url


CACHE_PATH = Path("data/open_source_cache.json")
CACHE_SECONDS = 24 * 60 * 60
NEGATIVE_CACHE_SECONDS = 30 * 60
CODE_URL_PATTERN = re.compile(
    r"https://(?:www\.)?(?:github\.com|gitlab\.com)/[^\s<>'\")\]}]+",
    re.IGNORECASE,
)
MAJOR_ORGANIZATIONS = (
    "openai",
    "anthropic",
    "google",
    "deepmind",
    "meta",
    "fair",
    "microsoft",
    "nvidia",
    "adobe",
    "amazon",
    "apple",
    "bytedance",
    "tencent",
    "alibaba",
    "baidu",
    "xai",
    "waymo",
    "tesla",
    "moonshot",
    "shanghai ai laboratory",
    "beijing academy of artificial intelligence",
)
TOP_ACADEMIC_ORGANIZATIONS = (
    "massachusetts institute of technology",
    "mit",
    "stanford university",
    "carnegie mellon university",
    "university of california, berkeley",
    "uc berkeley",
    "university of oxford",
    "university of cambridge",
    "eth zurich",
    "eth zürich",
    "epfl",
    "princeton university",
    "cornell university",
    "university of toronto",
    "university of illinois urbana-champaign",
    "uiuc",
    "tsinghua university",
    "peking university",
    "zhejiang university",
    "shanghai jiao tong university",
    "university of science and technology of china",
    "chinese academy of sciences",
    "nanyang technological university",
    "national university of singapore",
    "mila",
    "vector institute",
    "allen institute for ai",
    "max planck institute",
)


def _load_cache() -> dict:
    try:
        value = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(value: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _paper_key(paper: dict) -> str:
    return str(
        paper.get("id")
        or paper.get("arxiv_id")
        or paper.get("paper_url")
        or paper.get("title")
        or ""
    ).strip()


def _normalize_repo_url(value: object) -> str:
    text = str(value or "").strip().rstrip(".,;:)")
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").casefold()
    parts = [part for part in parsed.path.split("/") if part]
    if host in {"github.com", "www.github.com"} and len(parts) >= 2:
        owner, repo = parts[0], parts[1].removesuffix(".git")
        if owner and repo and owner.casefold() not in {"features", "topics", "search"}:
            return f"https://github.com/{owner}/{repo}"
    if host in {"gitlab.com", "www.gitlab.com"} and len(parts) >= 2:
        stop = next(
            (index for index, part in enumerate(parts) if part in {"-", "tree", "blob"}),
            len(parts),
        )
        project = "/".join(parts[:stop]).removesuffix(".git")
        if "/" in project:
            return f"https://gitlab.com/{project}"
    return ""


def _extract_repo_urls(value: object) -> list[str]:
    result = []
    for match in CODE_URL_PATTERN.findall(str(value or "")):
        normalized = _normalize_repo_url(match)
        if normalized and normalized not in result:
            result.append(normalized)
    normalized = _normalize_repo_url(value)
    if normalized and normalized not in result:
        result.insert(0, normalized)
    return result


def _safe_project_url(value: object) -> str:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not host:
        return ""
    if host in {"localhost", "127.0.0.1", "0.0.0.0"} or host.endswith(".local"):
        return ""
    return parsed.geturl()


def _urls_from_page(url: str) -> list[str]:
    safe_url = _safe_project_url(url)
    if not safe_url:
        return []
    response = requests.get(
        safe_url,
        timeout=30,
        headers={"User-Agent": "HumanGroupBot/1.0 open-source verifier"},
    )
    response.raise_for_status()
    text = response.text[:2_000_000]
    urls = _extract_repo_urls(text)
    for href in re.findall(r'href=["\x27]([^"\x27]+)["\x27]', text, re.I):
        absolute = urllib.parse.urljoin(safe_url, href)
        normalized = _normalize_repo_url(absolute)
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls


def _urls_from_pdf(paper: dict) -> list[str]:
    pdf_url = _validated_pdf_url(paper)
    if not pdf_url:
        return []
    content = _download_pdf(pdf_url)
    document = fitz.open(stream=content, filetype="pdf")
    try:
        urls = []
        for index in range(min(4, document.page_count)):
            page = document.load_page(index)
            for link in page.get_links():
                normalized = _normalize_repo_url(link.get("uri"))
                if normalized and normalized not in urls:
                    urls.append(normalized)
            for normalized in _extract_repo_urls(page.get_text("text")):
                if normalized not in urls:
                    urls.append(normalized)
        return urls
    finally:
        document.close()


def _repo_matches_paper(metadata: dict, readme: str, paper: dict) -> bool:
    arxiv_id = str(paper.get("id") or paper.get("arxiv_id") or "").strip()
    title = str(paper.get("title") or "").strip()
    combined = " ".join(
        [
            str(metadata.get("name") or ""),
            str(metadata.get("full_name") or ""),
            str(metadata.get("description") or ""),
            str(metadata.get("homepage") or ""),
            readme[:80_000],
        ]
    ).casefold()
    if arxiv_id and arxiv_id in combined:
        return True
    significant = [
        word
        for word in re.findall(r"[a-z0-9]+", title.casefold())
        if len(word) >= 4 and word not in {"with", "from", "using", "based", "towards"}
    ]
    if len(significant) >= 3 and sum(word in combined for word in significant) >= min(5, len(significant)):
        return True
    acronym = title.split(":", 1)[0].strip().casefold() if ":" in title else ""
    return len(acronym) >= 3 and re.sub(r"[^a-z0-9]", "", acronym) in re.sub(
        r"[^a-z0-9]", "", combined
    )


def _verify_github(url: str, paper: dict) -> dict | None:
    parts = urllib.parse.urlparse(url).path.strip("/").split("/")
    if len(parts) != 2:
        return None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "HumanGroupBot/1.0",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(
        f"https://api.github.com/repos/{parts[0]}/{parts[1]}",
        timeout=30,
        headers=headers,
    )
    if response.status_code != 200:
        return None
    data = response.json()
    if data.get("private") or data.get("disabled"):
        return None
    readme_response = requests.get(
        f"https://api.github.com/repos/{parts[0]}/{parts[1]}/readme",
        timeout=30,
        headers=headers,
    )
    readme = ""
    if readme_response.status_code == 200:
        payload = readme_response.json()
        if str(payload.get("encoding") or "").casefold() == "base64":
            try:
                readme = base64.b64decode(payload.get("content") or "").decode(
                    "utf-8", errors="replace"
                )
            except (ValueError, TypeError):
                readme = ""
    if not _repo_matches_paper(data, readme, paper):
        return None
    return {
        "code_url": str(data.get("html_url") or url),
        "code_host": "GitHub",
        "repo_stars": int(data.get("stargazers_count") or 0),
        "repo_archived": bool(data.get("archived")),
    }


def _verify_gitlab(url: str, paper: dict) -> dict | None:
    project = urllib.parse.urlparse(url).path.strip("/")
    response = requests.get(
        "https://gitlab.com/api/v4/projects/" + urllib.parse.quote(project, safe=""),
        timeout=30,
        headers={"User-Agent": "HumanGroupBot/1.0"},
    )
    if response.status_code != 200:
        return None
    data = response.json()
    if str(data.get("visibility") or "").casefold() != "public":
        return None
    if not _repo_matches_paper(data, str(data.get("description") or ""), paper):
        return None
    return {
        "code_url": str(data.get("web_url") or url),
        "code_host": "GitLab",
        "repo_stars": int(data.get("star_count") or 0),
        "repo_archived": bool(data.get("archived")),
    }


def verify_repository(url: str, paper: dict) -> dict | None:
    normalized = _normalize_repo_url(url)
    if not normalized:
        return None
    host = (urllib.parse.urlparse(normalized).hostname or "").casefold()
    if host == "github.com":
        return _verify_github(normalized, paper)
    if host == "gitlab.com":
        return _verify_gitlab(normalized, paper)
    return None


def _organization_text(paper: dict) -> str:
    return " ".join(
        [
            str(paper.get("hf_organization") or ""),
            *(str(value) for value in paper.get("institutions", [])),
        ]
    ).casefold()


def _find_organization(organizations: str, names: tuple[str, ...]) -> str:
    for name in names:
        pattern = r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])"
        if re.search(pattern, organizations):
            return name
    return ""


def institution_impact(paper: dict) -> dict:
    """Return a deterministic source-impact tier from verified affiliations."""
    organizations = _organization_text(paper)
    industry = _find_organization(organizations, MAJOR_ORGANIZATIONS)
    if industry:
        return {
            "institution_impact_tier": 3,
            "institution_impact_label": "大公司/头部研究机构",
            "institution_impact_evidence": industry,
        }
    academic = _find_organization(organizations, TOP_ACADEMIC_ORGANIZATIONS)
    if academic:
        return {
            "institution_impact_tier": 2,
            "institution_impact_label": "顶级高校/研究机构",
            "institution_impact_evidence": academic,
        }
    return {
        "institution_impact_tier": 1,
        "institution_impact_label": "大团队",
        "institution_impact_evidence": "",
    }


def _large_team_evidence(paper: dict) -> str:
    authors = [str(value).strip() for value in paper.get("authors", []) if str(value).strip()]
    impact = institution_impact(paper)
    evidence = impact["institution_impact_evidence"]
    if impact["institution_impact_tier"] >= 2:
        return f"{impact['institution_impact_label']}：{evidence}；作者 {len(authors)} 人"
    if len(authors) >= 5:
        return f"作者团队 {len(authors)} 人"
    return ""


def enrich_open_source_paper(paper: dict) -> dict | None:
    """Return the paper only when public code and large-team evidence are verified."""
    team_evidence = _large_team_evidence(paper)
    if not team_evidence:
        # A small author list can still be an influential university/company paper.
        # Only candidates already confirmed by the LLM reach this function, so read
        # the official PDF affiliation before making the final team decision.
        from paper_metadata import enrich_paper_metadata

        paper = enrich_paper_metadata(paper)
        team_evidence = _large_team_evidence(paper)
        if not team_evidence:
            return None

    key = _paper_key(paper)
    cache = _load_cache()
    cached = cache.get(key) if key else None
    cache_age = (
        time.time() - float(cached.get("checked_at") or 0)
        if isinstance(cached, dict)
        else CACHE_SECONDS + 1
    )
    cache_ttl = (
        CACHE_SECONDS
        if isinstance(cached, dict) and cached.get("repository")
        else NEGATIVE_CACHE_SECONDS
    )
    if isinstance(cached, dict) and cache_age < cache_ttl:
        repository = cached.get("repository")
        if not repository:
            return None
        result = dict(paper)
        result.update(repository)
        result["open_source_verified"] = True
        result["large_team_verified"] = True
        result["team_evidence"] = team_evidence
        result.update(institution_impact(result))
        return result

    candidates = []
    for field in (
        "code_url",
        "hf_github_url",
        "github_url",
        "project_url",
        "hf_project_url",
        "comment",
        "abstract",
        "summary",
    ):
        for url in _extract_repo_urls(paper.get(field)):
            if url not in candidates:
                candidates.append(url)

    pages = [
        paper.get("paper_url"),
        paper.get("official_url"),
        paper.get("project_url"),
        paper.get("hf_project_url"),
    ]
    for page_url in pages:
        if candidates:
            break
        try:
            candidates.extend(_urls_from_page(str(page_url or "")))
        except Exception:
            continue
    if not candidates:
        try:
            candidates.extend(_urls_from_pdf(paper))
        except Exception as exc:
            print(f"论文代码链接 PDF 核验失败: {paper.get('title', '')}: {exc}", flush=True)

    repository = None
    for candidate in list(dict.fromkeys(candidates))[:6]:
        try:
            repository = verify_repository(candidate, paper)
        except Exception:
            repository = None
        if repository:
            break

    if key:
        cache[key] = {"checked_at": time.time(), "repository": repository}
        _save_cache(cache)
    if not repository:
        return None

    result = dict(paper)
    result.update(repository)
    result["open_source_verified"] = True
    result["large_team_verified"] = True
    result["team_evidence"] = team_evidence
    result.update(institution_impact(result))
    return result


def _parse_json_object(value: str) -> dict:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def llm_confirm_open_source_links(papers: list[dict]) -> dict[str, dict]:
    """Use web-enabled LLM research to confirm paper-to-repository ownership first."""
    if not papers:
        return {}
    candidates = [
        {
            "title": paper.get("title", ""),
            "arxiv_id": paper.get("id") or paper.get("arxiv_id") or "",
            "authors": list(paper.get("authors", []))[:12],
            "paper_url": paper.get("paper_url", ""),
            "known_code_signal": (
                paper.get("hf_github_url")
                or paper.get("code_url")
                or paper.get("hf_project_url")
                or ""
            ),
        }
        for paper in papers
    ]
    prompt = f"""
你是论文开源核验员。请联网逐篇确认下面论文是否已经公开了属于该论文的源代码仓库。
只接受公开 GitHub 或 GitLab 仓库；项目主页、论文 PDF、模型演示、空仓库、非官方复现都不算。
仓库 README、论文官方页、作者项目页或 arXiv 信息必须能明确把仓库与论文标题/arXiv ID 对应起来。

候选：{json.dumps(candidates, ensure_ascii=False)}

严格返回 JSON，不要 Markdown：
{{"papers":[{{
  "title":"必须与输入逐字一致",
  "is_open_source":true,
  "code_url":"规范的 GitHub/GitLab 仓库根地址；不能确认则为空",
  "evidence":"用一句话说明在哪个官方来源或 README 中确认了对应关系"
}}]}}
宁可返回 false，也不要猜测、补全或根据同名仓库推断。
"""
    allowed = {str(paper.get("title") or "") for paper in papers}
    has_known_signal = any(item.get("known_code_signal") for item in candidates)
    for attempt in range(2):
        try:
            payload = _parse_json_object(
                call_glm(prompt, timeout=300, web_search=True)
            )
        except Exception as exc:
            print(f"LLM 开源链接核验失败（第 {attempt + 1} 次）: {exc}", flush=True)
            continue
        result = {}
        for item in payload.get("papers", []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "")
            code_url = _normalize_repo_url(item.get("code_url"))
            evidence = str(item.get("evidence") or "").strip()
            if (
                title not in allowed
                or not item.get("is_open_source")
                or not code_url
                or not evidence
            ):
                continue
            result[title] = {
                "code_url": code_url,
                "llm_open_source_evidence": evidence,
                "llm_open_source_verified": True,
            }
        if result or not has_known_signal:
            return result
        print("LLM 未确认已知代码信号，自动复核一次", flush=True)
    return {}


def filter_open_source_large_team(papers: list[dict]) -> list[dict]:
    candidates = list(papers)
    candidates.sort(
        key=lambda paper: (
            institution_impact(paper)["institution_impact_tier"],
            bool(paper.get("conference_verified")),
            int(paper.get("hf_upvotes") or 0),
            len(paper.get("authors", [])),
        ),
        reverse=True,
    )
    confirmations = llm_confirm_open_source_links(candidates)
    result = []
    for paper in candidates:
        confirmation = confirmations.get(str(paper.get("title") or ""))
        if not confirmation:
            print(f"跳过 LLM 未确认开源论文: {paper.get('title', '')}", flush=True)
            continue
        candidate = {**paper, **confirmation}
        enriched = enrich_open_source_paper(candidate)
        if enriched:
            result.append(enriched)
        else:
            print(
                f"跳过非核验开源/非大团队论文: {paper.get('title', '')}",
                flush=True,
            )
    return result
