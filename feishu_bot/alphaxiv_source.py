from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from paper_search import _query_arxiv


API_URL = "https://api.alphaxiv.org/mcp/v1"
CACHE_PATH = Path("data/alphaxiv_daily.json")
ARXIV_ID_PATTERN = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)")
TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_KEYWORDS = [
    "agent harness",
    "AI infrastructure",
    "digital human",
    "motion generation",
    "embodied AI",
    "world model",
    "video generation",
    "human motion",
    "panoramic vision",
]


def _json_rpc_payload(response: requests.Response) -> dict:
    response.raise_for_status()
    if not response.content:
        return {}
    content_type = str(response.headers.get("content-type") or "").casefold()
    if "text/event-stream" not in content_type:
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    messages = []
    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        value = line[5:].strip()
        if not value or value == "[DONE]":
            continue
        try:
            item = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            messages.append(item)
    return messages[-1] if messages else {}


class AlphaXivMCPClient:
    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "HumanGroupBot/1.0 alphaXiv paper discovery",
        }
        self.session_id = ""
        self.request_id = 0

    def _call(self, method: str, params: dict | None = None, *, notification=False) -> dict:
        self.request_id += 1
        payload = {"jsonrpc": "2.0", "method": method}
        if not notification:
            payload["id"] = self.request_id
        if params is not None:
            payload["params"] = params
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        response = self.session.post(API_URL, headers=headers, json=payload, timeout=180)
        if response.headers.get("Mcp-Session-Id"):
            self.session_id = str(response.headers["Mcp-Session-Id"])
        return _json_rpc_payload(response)

    def initialize(self) -> None:
        payload = self._call(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "HumanGroupBot", "version": "1.0"},
            },
        )
        if payload.get("error"):
            raise RuntimeError(f"alphaXiv MCP 初始化失败：{payload['error']}")
        self._call("notifications/initialized", notification=True)

    def discover(self, topics: list[str], published_after: str) -> dict:
        self.initialize()
        topic_text = "、".join(str(value).strip() for value in topics if str(value).strip())
        payload = self._call(
            "tools/call",
            {
                "name": "discover_papers",
                "arguments": {
                    "keywords": DEFAULT_KEYWORDS,
                    "question": (
                        "Find the strongest recent research papers relevant to "
                        f"{topic_text or 'digital humans, motion generation, embodied AI, world models, video generation, and panoramic vision'}. "
                        "Use two discovery tracks: influential general-AI work from major AI companies or top labs "
                        "regardless of exact topic, plus strong work in the named focus areas. Prioritize technically "
                        "substantial papers with official public code. "
                        "Return arXiv papers only."
                    ),
                    "difficulty": 5,
                    "published_after": published_after,
                    "prioritize": "recency",
                },
            },
        )
        if payload.get("error"):
            raise RuntimeError(f"alphaXiv 论文发现失败：{payload['error']}")
        return payload.get("result") or {}


def _extract_arxiv_ids(value: object) -> list[str]:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    result = []
    for arxiv_id in ARXIV_ID_PATTERN.findall(text):
        if arxiv_id not in result:
            result.append(arxiv_id)
    return result[:15]


def _load_cache(today: str) -> list[str] | None:
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("date") != today:
        return None
    return _extract_arxiv_ids(payload.get("arxiv_ids") or [])


def _save_cache(today: str, arxiv_ids: list[str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(
            {"date": today, "fetched_at": datetime.now(TIMEZONE).isoformat(), "arxiv_ids": arxiv_ids},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def get_alphaxiv_candidates(topics: list[str] | None = None) -> list[dict]:
    """Query alphaXiv once per Beijing day, then resolve every result through arXiv."""
    api_key = os.getenv("ALPHAXIV_API_KEY", "").strip()
    if not api_key:
        print("alphaXiv 未启用：缺少 ALPHAXIV_API_KEY", flush=True)
        return []
    now = datetime.now(TIMEZONE)
    today = now.date().isoformat()
    arxiv_ids = _load_cache(today)
    if arxiv_ids is None:
        result = AlphaXivMCPClient(api_key).discover(
            list(topics or []),
            (now.date() - timedelta(days=14)).isoformat(),
        )
        arxiv_ids = _extract_arxiv_ids(result)
        _save_cache(today, arxiv_ids)
    if not arxiv_ids:
        return []
    papers = _query_arxiv({"id_list": ",".join(arxiv_ids)})
    positions = {arxiv_id: index for index, arxiv_id in enumerate(arxiv_ids)}
    papers.sort(key=lambda paper: positions.get(str(paper.get("id") or ""), 999))
    for paper in papers:
        paper["discovery_source"] = "alphaXiv"
        paper["alphaxiv_url"] = f"https://www.alphaxiv.org/overview/{paper.get('id', '')}"
    return papers
