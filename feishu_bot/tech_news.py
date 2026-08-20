from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

from automation_llm import call_automation_llm as call_glm


DB_PATH = Path(__file__).resolve().parent / "data" / "tech_news.db"
SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_PUSH_TIME = "21:00"
NEWS_LOOKBACK_DAYS = 14
DEFAULT_PUBLIC_ACCOUNTS = [
    "量子位",
    "机器之心",
    "新智元",
    "CVer",
    "刘聪NLP",
    "具身智能之心",
]
DEFAULT_COMPANIES = [
    "Moonshot/Kimi",
    "DeepSeek",
    "智谱 GLM",
    "MiniMax",
    "NVIDIA",
    "AMD AI",
    "Groq",
    "Cerebras",
    "OpenAI",
    "Anthropic/Claude",
    "阿里/Qwen",
    "字节/豆包",
    "腾讯/混元",
    "Google AI/Gemini",
    "Google DeepMind",
    "Meta AI",
    "Microsoft AI",
    "Amazon/AWS AI",
    "Apple ML",
    "Hugging Face",
    "Mistral AI",
    "Cohere",
    "Perplexity",
    "Stability AI",
    "Runway",
    "Figure AI",
    "Physical Intelligence",
    "Unitree",
    "xAI",
]
OFFICIAL_X_ACCOUNTS = {
    "OpenAI": ["OpenAI", "OpenAIDevs"],
    "Anthropic/Claude": ["AnthropicAI"],
    "NVIDIA": ["nvidia"],
    "AMD AI": ["AMD"],
    "Groq": ["GroqInc"],
    "Cerebras": ["CerebrasSystems"],
    "DeepSeek": ["deepseek_ai"],
    "阿里/Qwen": ["Alibaba_Qwen"],
    "腾讯/混元": ["TencentGlobal"],
    "Google AI/Gemini": ["GoogleAI"],
    "Google DeepMind": ["GoogleDeepMind"],
    "Meta AI": ["AIatMeta"],
    "Microsoft AI": ["MSFTResearch", "Microsoft"],
    "Amazon/AWS AI": ["AWSCloud"],
    "Hugging Face": ["huggingface"],
    "Mistral AI": ["mistralai"],
    "Cohere": ["cohere"],
    "Perplexity": ["perplexity_ai"],
    "Stability AI": ["StabilityAI"],
    "Runway": ["runwayml"],
    "Figure AI": ["Figure_robot"],
    "Physical Intelligence": ["physical_int"],
    "Unitree": ["UnitreeRobotics"],
    "xAI": ["spacexai", "grok"],
}
DEFAULT_X_ACCOUNTS = list(
    dict.fromkeys(
        handle
        for handles in OFFICIAL_X_ACCOUNTS.values()
        for handle in handles
    )
)
if "thsottiaux" not in DEFAULT_X_ACCOUNTS:
    DEFAULT_X_ACCOUNTS.append("thsottiaux")

# These high-signal accounts are scanned directly through the configured
# proxy. This avoids relying on an LLM/web-search provider to discover post URLs.
DIRECT_X_DISCOVERY_HANDLES = {"openai", "openaidevs", "thsottiaux"}
X_HANDLE_TO_COMPANY = {
    handle.casefold(): company
    for company, handles in OFFICIAL_X_ACCOUNTS.items()
    for handle in handles
}
COMPANY_DOMAINS = {
    "Moonshot/Kimi": {"moonshot.cn", "kimi.com"},
    "DeepSeek": {"deepseek.com", "github.com"},
    "智谱 GLM": {"zhipuai.cn", "bigmodel.cn"},
    "MiniMax": {"minimaxi.com", "minimax.io"},
    "NVIDIA": {"nvidia.com"},
    "AMD AI": {"amd.com"},
    "Groq": {"groq.com"},
    "Cerebras": {"cerebras.ai"},
    "OpenAI": {"openai.com"},
    "Anthropic/Claude": {"anthropic.com", "claude.com"},
    "阿里/Qwen": {
        "alibaba.com", "aliyun.com", "alibabacloud.com", "qwen.ai", "github.com",
    },
    "字节/豆包": {"bytedance.com", "volcengine.com", "doubao.com"},
    "腾讯/混元": {"tencent.com", "cloud.tencent.com"},
    "Google AI/Gemini": {"blog.google", "ai.google.dev", "developers.googleblog.com"},
    "Google DeepMind": {"deepmind.google", "blog.google", "googleblog.com"},
    "Meta AI": {"ai.meta.com", "about.fb.com", "meta.com"},
    "Microsoft AI": {"microsoft.com"},
    "Amazon/AWS AI": {"aws.amazon.com", "amazon.science"},
    "Apple ML": {"machinelearning.apple.com", "apple.com"},
    "Hugging Face": {"huggingface.co"},
    "Mistral AI": {"mistral.ai"},
    "Cohere": {"cohere.com"},
    "Perplexity": {"perplexity.ai"},
    "Stability AI": {"stability.ai"},
    "Runway": {"runwayml.com"},
    "Figure AI": {"figure.ai"},
    "Physical Intelligence": {"physicalintelligence.company"},
    "Unitree": {"unitree.com"},
    "xAI": {"x.ai"},
}

# Direct official feeds supplement model-assisted web search. Feed entries are
# still checked against the publisher's allow-listed domain and publication
# date before they can be sent.
OFFICIAL_NEWS_FEEDS = {
    "OpenAI": ["https://openai.com/news/rss.xml"],
    "Google AI/Gemini": ["https://blog.google/technology/ai/rss/"],
    "Google DeepMind": ["https://deepmind.google/blog/rss.xml"],
    "NVIDIA": ["https://blogs.nvidia.com/feed/"],
    "Microsoft AI": ["https://www.microsoft.com/en-us/research/feed/"],
    "Hugging Face": ["https://huggingface.co/blog/feed.xml"],
    "Amazon/AWS AI": [
        "https://aws.amazon.com/blogs/machine-learning/feed/",
        "https://www.amazon.science/index.rss",
    ],
    "Apple ML": ["https://machinelearning.apple.com/rss.xml"],
    "DeepSeek": ["https://github.com/deepseek-ai/deepseek-harness/releases.atom"],
    "阿里/Qwen": ["https://github.com/QwenLM/Qwen3/releases.atom"],
}

NEWS_CATEGORY_ORDER = (
    "模型与研究",
    "产品与 Agent",
    "算力与芯片",
    "机器人与具身",
    "资本与组织",
    "治理与安全",
    "企业动态",
)
NEWS_CATEGORY_ICONS = {
    "模型与研究": "🧠",
    "产品与 Agent": "🛠️",
    "算力与芯片": "⚡",
    "机器人与具身": "🤖",
    "资本与组织": "💼",
    "治理与安全": "🛡️",
    "企业动态": "🏢",
}
NEWS_CATEGORY_KEYWORDS = {
    "机器人与具身": (
        "robot", "robotics", "humanoid", "embodied", "具身", "机器人", "人形",
    ),
    "算力与芯片": (
        "gpu", "cuda", "chip", "semiconductor", "inference", "算力", "芯片", "推理服务",
    ),
    "资本与组织": (
        "funding", "financing", "acquisition", "revenue", "earnings", "融资", "并购", "财报", "估值",
    ),
    "治理与安全": (
        "regulation", "policy", "safety", "security", "governance", "监管", "政策", "安全", "治理", "标准",
    ),
    "产品与 Agent": (
        "agent", "assistant", "copilot", "codex", "api", "product", "智能体", "助手", "产品",
    ),
    "模型与研究": (
        "model", "research", "paper", "benchmark", "gpt", "claude", "qwen", "gemini", "模型", "论文", "研究", "基准", "开源",
    ),
}


def _news_category(item: dict) -> str:
    requested = str(item.get("category") or "").strip()
    if requested in NEWS_CATEGORY_ORDER:
        return requested
    text = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("summary") or ""),
            " ".join(str(value) for value in item.get("entities", [])),
        ]
    ).casefold()
    for category, keywords in NEWS_CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "企业动态"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_tech_news() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_subscriptions (
                chat_id TEXT PRIMARY KEY,
                public_accounts TEXT NOT NULL,
                companies TEXT NOT NULL,
                x_accounts TEXT NOT NULL,
                push_time TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(news_subscriptions)").fetchall()
        }
        if "x_accounts" not in columns:
            conn.execute(
                "ALTER TABLE news_subscriptions "
                "ADD COLUMN x_accounts TEXT NOT NULL DEFAULT '[]'"
            )
            conn.execute(
                "UPDATE news_subscriptions SET x_accounts=?",
                (json.dumps(DEFAULT_X_ACCOUNTS, ensure_ascii=False),),
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_runs (
                chat_id TEXT NOT NULL,
                run_date TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, run_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_deliveries (
                chat_id TEXT NOT NULL,
                url TEXT NOT NULL,
                delivered_at TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT '',
                entities_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (chat_id, url)
            )
            """
        )
        delivery_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(news_deliveries)").fetchall()
        }
        for column, declaration in {
            "title": "TEXT NOT NULL DEFAULT ''",
            "summary": "TEXT NOT NULL DEFAULT ''",
            "publisher": "TEXT NOT NULL DEFAULT ''",
            "entities_json": "TEXT NOT NULL DEFAULT '[]'",
        }.items():
            if column not in delivery_columns:
                conn.execute(
                    f"ALTER TABLE news_deliveries ADD COLUMN {column} {declaration}"
                )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_archive_documents (
                year INTEGER PRIMARY KEY,
                document_id TEXT NOT NULL,
                url TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def _normalize_names(values: list[str], *, limit: int = 30) -> list[str]:
    result = []
    seen = set()
    for value in values:
        name = re.sub(r"\s+", " ", str(value)).strip(" ，、,;；")
        key = name.casefold()
        if not name or len(name) > 60 or key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result[:limit]


def _normalize_x_handles(values: list[str], *, limit: int = 40) -> list[str]:
    result = []
    seen = set()
    for value in values:
        handle = str(value or "").strip().lstrip("@").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
            continue
        key = handle.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(handle)
    return result[:limit]


def _normalize_time(value: str) -> str:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value))
    if not match:
        raise ValueError("资讯推送时间格式不正确")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("资讯推送时间格式不正确")
    return f"{hour:02d}:{minute:02d}"


def get_news_subscription(chat_id: str, *, create: bool = True) -> dict | None:
    init_tech_news()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM news_subscriptions WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if row is None and create:
            now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
            conn.execute(
                """
                INSERT INTO news_subscriptions
                (chat_id, public_accounts, companies, x_accounts, push_time, enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    chat_id,
                    json.dumps(DEFAULT_PUBLIC_ACCOUNTS, ensure_ascii=False),
                    json.dumps(DEFAULT_COMPANIES, ensure_ascii=False),
                    json.dumps(DEFAULT_X_ACCOUNTS, ensure_ascii=False),
                    DEFAULT_PUSH_TIME,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM news_subscriptions WHERE chat_id=?", (chat_id,)
            ).fetchone()
    if row is None:
        return None
    value = dict(row)
    value["public_accounts"] = _normalize_names(
        json.loads(value["public_accounts"])
    )
    value["companies"] = _normalize_names(json.loads(value["companies"]))
    value["x_accounts"] = _normalize_x_handles(
        json.loads(value.get("x_accounts") or "[]")
    )
    value["enabled"] = bool(value["enabled"])
    return value


def ensure_default_news_subscription() -> None:
    # News can target a different group from the paper bot. Keep the legacy
    # FEISHU_CHAT_ID fallback for existing installations.
    chat_id = (
        os.getenv("FEISHU_NEWS_CHAT_ID", "").strip()
        or os.getenv("FEISHU_CHAT_ID", "").strip()
    )
    if chat_id:
        get_news_subscription(chat_id, create=True)


def update_news_subscription(chat_id: str, **changes) -> dict:
    get_news_subscription(chat_id, create=True)
    updates = {}
    if "public_accounts" in changes:
        updates["public_accounts"] = json.dumps(
            _normalize_names(list(changes["public_accounts"])), ensure_ascii=False
        )
    if "companies" in changes:
        updates["companies"] = json.dumps(
            _normalize_names(list(changes["companies"])), ensure_ascii=False
        )
    if "x_accounts" in changes:
        updates["x_accounts"] = json.dumps(
            _normalize_x_handles(list(changes["x_accounts"])), ensure_ascii=False
        )
    if "push_time" in changes:
        updates["push_time"] = _normalize_time(changes["push_time"])
    if "enabled" in changes:
        updates["enabled"] = int(bool(changes["enabled"]))
    updates["updated_at"] = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "UPDATE news_subscriptions SET "
            + ", ".join(f"{key}=?" for key in updates)
            + " WHERE chat_id=?",
            [*updates.values(), chat_id],
        )
    return get_news_subscription(chat_id, create=False)


def format_news_subscription(subscription: dict) -> str:
    return (
        "📰 AI 科技资讯订阅\n\n"
        f"状态：{'已启用' if subscription['enabled'] else '已暂停'}\n"
        f"公众号：{'、'.join(subscription['public_accounts']) or '尚未设置'}\n"
        f"科技企业：{'、'.join(subscription['companies']) or '尚未设置'}\n"
        f"官方 X：{'、'.join('@' + item for item in subscription.get('x_accounts', [])) or '尚未设置'}\n"
        f"时间：{subscription['push_time']}（北京时间）\n"
        "规则：微信公众号原文、企业官网与官方 X 原帖优先，自动核验并跨来源去重"
    )


def handle_news_subscription_command(chat_id: str, text: str) -> str | None:
    command = text.strip()
    match = re.fullmatch(r"订阅公众号[：:\s]+(.+)", command)
    if match:
        accounts = _normalize_names(re.split(r"[，,、;；]+", match.group(1)))
        if not accounts:
            return "请填写公众号全名。"
        value = update_news_subscription(
            chat_id, public_accounts=accounts, enabled=True
        )
        return "公众号订阅已更新。\n\n" + format_news_subscription(value)

    match = re.fullmatch(r"订阅AI公司[：:\s]+(.+)", command, re.I)
    if match:
        companies = _normalize_names(re.split(r"[，,、;；]+", match.group(1)))
        if not companies:
            return "请填写需要关注的科技企业。"
        value = update_news_subscription(chat_id, companies=companies, enabled=True)
        return "科技企业订阅已更新。\n\n" + format_news_subscription(value)

    match = re.fullmatch(r"订阅(?:官方)?X账号[：:\s]+(.+)", command, re.I)
    if match:
        handles = _normalize_x_handles(re.split(r"[，,、;；\s]+", match.group(1)))
        if not handles:
            return "请填写有效的 X 账号，例如 @OpenAI、@AnthropicAI。"
        value = update_news_subscription(chat_id, x_accounts=handles, enabled=True)
        return "官方 X 账号订阅已更新。\n\n" + format_news_subscription(value)

    match = re.fullmatch(r"资讯推送时间[：:\s]+(.+)", command)
    if match:
        try:
            value = update_news_subscription(
                chat_id, push_time=match.group(1), enabled=True
            )
        except ValueError:
            return "资讯推送时间格式不正确，请使用 00:00 到 23:59。"
        return "资讯推送时间已更新。\n\n" + format_news_subscription(value)

    if command in {"查看资讯订阅", "查看公众号订阅"}:
        return format_news_subscription(get_news_subscription(chat_id, create=True))
    if command in {"暂停资讯推送", "暂停公众号推送"}:
        value = update_news_subscription(chat_id, enabled=False)
        return "AI 科技资讯推送已暂停。\n\n" + format_news_subscription(value)
    if command in {"恢复资讯推送", "开启资讯推送"}:
        value = update_news_subscription(chat_id, enabled=True)
        return "AI 科技资讯推送已恢复。\n\n" + format_news_subscription(value)
    return None


def _parse_json_object(value: str) -> dict:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    result = json.loads(text, strict=False)
    return result if isinstance(result, dict) else {}


def _canonical_url(value: object) -> str:
    raw = str(value or "").strip()
    if re.search(r"(?:placeholder|example|dummy|sample_?url)", raw, re.I):
        return ""
    parsed = urllib.parse.urlparse(raw)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not host:
        return ""
    if host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        match = re.fullmatch(
            r"/([A-Za-z0-9_]{1,15})/status/(\d+)(?:/.*)?", parsed.path
        )
        if not match:
            return ""
        return f"https://x.com/{match.group(1)}/status/{match.group(2)}"
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [
        (key, item)
        for key, item in query
        if not key.casefold().startswith("utm_")
    ]
    return urllib.parse.urlunparse(
        ("https", host, parsed.path, "", urllib.parse.urlencode(query), "")
    )


def _host_matches(host: str, domains: set[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _x_status_parts(url: str) -> tuple[str, str] | None:
    canonical = _canonical_url(url)
    match = re.fullmatch(
        r"https://x\.com/([A-Za-z0-9_]{1,15})/status/(\d+)", canonical
    )
    return (match.group(1), match.group(2)) if match else None


def _item_source_type(item: dict, subscription: dict) -> str:
    url = _canonical_url(item.get("url"))
    host = (urllib.parse.urlparse(url).hostname or "").casefold()
    publisher = str(item.get("publisher") or "").strip()
    accounts = {value.casefold() for value in subscription["public_accounts"]}
    if host == "mp.weixin.qq.com" and publisher.casefold() in accounts:
        return "公众号"
    x_parts = _x_status_parts(url)
    allowed_x = {
        value.casefold() for value in subscription.get("x_accounts", [])
    }
    if x_parts and x_parts[0].casefold() in allowed_x:
        return "官方 X"
    allowed = COMPANY_DOMAINS.get(publisher, set())
    if allowed and _host_matches(host, allowed):
        return "企业官方"
    return ""


def _strip_html_fragment(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[ \t]+", " ", html.unescape(text)).strip()


def _feed_child_text(entry: ElementTree.Element, names: set[str]) -> str:
    for child in entry.iter():
        local_name = str(child.tag).rsplit("}", 1)[-1].casefold()
        if local_name in names and child.text:
            return str(child.text).strip()
    return ""


def _feed_entry_url(entry: ElementTree.Element, feed_url: str) -> str:
    for child in entry.iter():
        if str(child.tag).rsplit("}", 1)[-1].casefold() != "link":
            continue
        candidate = str(child.attrib.get("href") or child.text or "").strip()
        relation = str(child.attrib.get("rel") or "alternate").casefold()
        if candidate and relation in {"", "alternate"}:
            return urllib.parse.urljoin(feed_url, candidate)
    return ""


def _feed_date(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _read_official_feed(publisher: str, feed_url: str) -> list[dict]:
    try:
        response = requests.get(
            feed_url,
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 HumanGroupBot/1.0"},
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    except (requests.RequestException, ElementTree.ParseError):
        return []
    result = []
    entries = [
        element
        for element in root.iter()
        if str(element.tag).rsplit("}", 1)[-1].casefold() in {"item", "entry"}
    ]
    for entry in entries[:12]:
        title = _strip_html_fragment(_feed_child_text(entry, {"title"}))
        summary = _strip_html_fragment(
            _feed_child_text(entry, {"description", "summary", "content"})
        )
        published_date = _feed_date(
            _feed_child_text(entry, {"pubdate", "published", "updated", "date"})
        )
        url = _feed_entry_url(entry, feed_url)
        if not title or not summary or not published_date or not url:
            continue
        result.append(
            {
                "title": title,
                "publisher": publisher,
                "published_date": published_date,
                "url": url,
                "summary": summary[:320],
                "why_it_matters": "",
                "entities": [publisher],
            }
        )
    return result


def _discover_official_feed_items(subscription: dict) -> list[dict]:
    """Read allow-listed first-party RSS/Atom feeds without search discovery."""
    subscribed = set(subscription.get("companies", []))
    tasks = [
        (publisher, feed_url)
        for publisher, feed_urls in OFFICIAL_NEWS_FEEDS.items()
        if publisher in subscribed
        for feed_url in feed_urls
    ]
    if not tasks:
        return []
    result = []
    with ThreadPoolExecutor(max_workers=min(8, len(tasks))) as executor:
        futures = [
            executor.submit(_read_official_feed, publisher, feed_url)
            for publisher, feed_url in tasks
        ]
        for future in futures:
            try:
                result.extend(future.result())
            except Exception:
                continue
    return result


def _verify_x_post(item: dict, allowed_handles: list[str]) -> dict | None:
    parts = _x_status_parts(str(item.get("url") or ""))
    if not parts:
        return None
    expected_handle, _ = parts
    allowed = {value.casefold() for value in allowed_handles}
    if expected_handle.casefold() not in allowed:
        return None
    proxy_url = os.getenv("X_PROXY_URL", "").strip()
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    try:
        response = requests.get(
            "https://publish.x.com/oembed",
            params={
                "url": _canonical_url(item.get("url")),
                "omit_script": "true",
                "dnt": "true",
            },
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0 HumanGroupBot/1.0"},
            proxies=proxies,
        )
        if response.status_code != 200:
            return None
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    author_url = _canonical_url(
        str(payload.get("author_url") or "") + "/status/0"
    )
    author_parts = _x_status_parts(author_url)
    if not author_parts or author_parts[0].casefold() != expected_handle.casefold():
        return None
    embed_html = str(payload.get("html") or "")
    paragraph = re.search(r"<p\b[^>]*>(.*?)</p>", embed_html, flags=re.I | re.S)
    if not paragraph:
        return None
    source_text = _strip_html_fragment(paragraph.group(1))
    meaningful = re.sub(
        r"(?:https?://\S+|pic\.(?:twitter|x)\.com/\S+)", "", source_text, flags=re.I
    ).strip()
    if len(meaningful) < 12:
        return None
    date_match = re.search(
        r">([A-Z][a-z]+ \d{1,2}, \d{4})</a>\s*</blockquote>", embed_html
    )
    published_date = ""
    if date_match:
        try:
            published_date = datetime.strptime(
                date_match.group(1), "%B %d, %Y"
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass
    actual_company = X_HANDLE_TO_COMPANY.get(expected_handle.casefold())
    title_text = re.sub(r"\s+", " ", meaningful).strip()
    result = dict(item)
    result.update(
        {
            "url": _canonical_url(item.get("url")),
            "title": f"@{expected_handle}：{title_text[:90]}",
            "publisher": actual_company
            or str(payload.get("author_name") or f"@{expected_handle}"),
            "x_handle": expected_handle,
            "source_text": source_text[:1200],
        }
    )
    if published_date:
        result["published_date"] = published_date
    return result


def _discover_direct_x_items(subscription: dict) -> list[dict]:
    """Discover recent X status URLs directly from selected public profiles."""
    proxy_url = os.getenv("X_PROXY_URL", "").strip()
    if not proxy_url:
        return []
    proxies = {"http": proxy_url, "https": proxy_url}
    handles = [
        handle
        for handle in subscription.get("x_accounts", [])
        if handle.casefold() in DIRECT_X_DISCOVERY_HANDLES
    ]
    result = []
    for handle in handles:
        try:
            response = requests.get(
                f"https://x.com/{handle}",
                timeout=25,
                # X serves a tiny fallback shell to bot-identifying user agents;
                # a regular browser UA exposes the public status links.
                headers={"User-Agent": "Mozilla/5.0"},
                proxies=proxies,
            )
            if response.status_code != 200:
                continue
        except requests.RequestException:
            continue
        status_ids = list(
            dict.fromkeys(
                re.findall(
                    rf"/{re.escape(handle)}/status/(\d+)",
                    response.text,
                    flags=re.I,
                )
            )
        )[-8:]
        result.extend(
            {
                "title": f"@{handle} 官方 X 原帖",
                "publisher": f"@{handle}",
                "x_handle": handle,
                "published_date": "",
                "url": f"https://x.com/{handle}/status/{status_id}",
                "summary": "官方 X 原帖，正文将在发送前再次核验。",
                "why_it_matters": "",
                "entities": [handle],
            }
            for status_id in status_ids
        )
    return result


def _event_tokens(item: dict) -> set[str]:
    text = f"{item.get('title', '')} {item.get('summary', '')}".casefold()
    latin = {
        value
        for value in re.findall(r"[a-z0-9][a-z0-9._+-]{2,}", text)
        if value not in {"official", "launches", "announces", "update"}
    }
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    trigrams = {
        chinese[index : index + 3]
        for index in range(max(0, len(chinese) - 2))
    }
    return latin | trigrams


def _same_event(left: dict, right: dict) -> bool:
    left_tokens, right_tokens = _event_tokens(left), _event_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / min(
        len(left_tokens), len(right_tokens)
    )
    same_publisher = str(left.get("publisher", "")).casefold() == str(
        right.get("publisher", "")
    ).casefold()
    shared_entities = {
        value.casefold() for value in left.get("entities", [])
    } & {value.casefold() for value in right.get("entities", [])}
    return (same_publisher and overlap >= 0.62) or (
        bool(shared_entities) and overlap >= 0.78
    )


def _deduplicate_events(items: list[dict]) -> list[dict]:
    source_rank = {"企业官方": 3, "官方 X": 2, "公众号": 1}
    result: list[dict] = []
    for item in items:
        duplicate_index = next(
            (index for index, existing in enumerate(result) if _same_event(item, existing)),
            None,
        )
        if duplicate_index is None:
            result.append(item)
            continue
        if source_rank.get(item.get("source_type", ""), 0) > source_rank.get(
            result[duplicate_index].get("source_type", ""), 0
        ):
            result[duplicate_index] = item
    return result


def _page_is_accessible_and_consistent(item: dict, source_type: str) -> bool:
    url = _canonical_url(item.get("url"))
    try:
        response = requests.get(
            url,
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0 HumanGroupBot/1.0"},
        )
        if response.status_code >= 400:
            return False
    except requests.RequestException:
        return False
    page_text = html.unescape(response.text[:2_000_000]).casefold()
    publisher = str(item.get("publisher") or "").strip().casefold()
    title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip().casefold()
    normalized_page = re.sub(r"\s+", " ", page_text)
    title_matches = bool(title and title in normalized_page)
    if not title_matches:
        latin_words = [
            word
            for word in re.findall(r"[a-z0-9]+", title)
            if len(word) >= 4
            and word not in {"with", "from", "that", "this", "official", "update"}
        ]
        if latin_words:
            required = min(3, max(1, len(latin_words) // 2))
            title_matches = sum(word in normalized_page for word in latin_words) >= required
        chinese_chunks = re.findall(r"[\u4e00-\u9fff]{4,}", title)
        if chinese_chunks:
            title_matches = title_matches or any(
                chunk[: min(8, len(chunk))] in normalized_page
                for chunk in chinese_chunks
            )
    if source_type == "公众号":
        return bool(publisher and publisher in normalized_page and title_matches)
    return title_matches


def collect_tech_news(
    subscription: dict,
    *,
    now: datetime | None = None,
    verify_pages: bool = True,
    lookback_days: int = NEWS_LOOKBACK_DAYS,
) -> list[dict]:
    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    lookback_days = max(1, min(int(lookback_days), 180))
    today = current.strftime("%Y-%m-%d")
    start_date = (current - timedelta(days=lookback_days - 1)).strftime(
        "%Y-%m-%d"
    )
    accounts = subscription["public_accounts"]
    companies = subscription["companies"]
    x_accounts = subscription.get("x_accounts", [])
    batches = [
        (accounts[index : index + 3], [], [])
        for index in range(0, len(accounts), 3)
    ] + [
        ([], companies[index : index + 5], [])
        for index in range(0, len(companies), 5)
    ] + [
        ([], [], x_accounts[index : index + 5])
        for index in range(0, len(x_accounts), 5)
    ]
    raw_items = []
    for batch_accounts, batch_companies, batch_x_accounts in batches:
        prompt = f"""
你是严格的 AI 科技情报编辑。联网检索 {start_date} 至 {today} 新发布的内容。

本批微信公众号：{json.dumps(batch_accounts, ensure_ascii=False)}
本批科技企业：{json.dumps(batch_companies, ensure_ascii=False)}
本批官方 X 账号：{json.dumps(['@' + value for value in batch_x_accounts], ensure_ascii=False)}

来源规则：
1. 微信公众号内容必须给出 mp.weixin.qq.com 原文，并确认公众号名称与输入完全一致。
2. 企业新闻优先企业官网 Newsroom、Blog、Research 或官方发布页，不能用搜索结果页或聚合页。
3. X 动态只能给出本批账号自己的原始帖子直链，格式必须是 https://x.com/账号/status/数字ID；拒绝回复、转帖、搜索页和个人主页。
4. 只收录 AI 模型、开源、产品、算力芯片、Agent、机器人、融资并购或重要治理动态。
5. 同一事件只保留信息最直接的一条。没有可靠直链就不要返回。
6. 摘要和意义只能依据原文；不允许根据标题补写数字、性能或发布日期。

严格返回 JSON，不要 Markdown：
{{"items":[{{
  "title":"原文标题；X 帖子可概括原帖首句",
  "publisher":"必须是输入中的公众号、企业名称或X账号",
  "x_handle":"仅X帖子填写不带@的账号，其他来源留空",
  "published_date":"YYYY-MM-DD",
  "url":"原文 HTTPS 直链",
  "summary":"80至140字中文事实摘要",
  "why_it_matters":"一句话说明对 AI 产业或研究的意义",
  "category":"只能从：模型与研究、产品与 Agent、算力与芯片、机器人与具身、资本与组织、治理与安全、企业动态 中选择",
  "entities":["涉及企业或模型"]
}}]}}
请分别检索本批每个来源，最多返回 5 条；宁可少报，不要猜测。
"""
        search_prompt = (
            f"分别检索这些公众号 {batch_accounts}、科技企业 {batch_companies} "
            f"和官方 X 账号 {batch_x_accounts} "
            f"最近 {lookback_days} 天的 AI 原文。优先 mp.weixin.qq.com 原文以及企业官网 "
            "newsroom/blog/research 或 x.com/账号/status/数字ID；拒绝聚合转载、无日期页面、"
            "X 搜索页、回复和无法确认发布者的链接。"
            "搜索结果：{search_result}"
        )
        try:
            payload = _parse_json_object(
                call_glm(
                    prompt,
                    timeout=360,
                    web_search=True,
                    search_prompt=search_prompt,
                    search_count=20,
                )
            )
        except Exception as exc:
            print(
                "AI 科技资讯分批检索失败 "
                f"{batch_accounts or batch_companies or batch_x_accounts}: {exc}",
                flush=True,
            )
            continue
        raw_items.extend(payload.get("items", [])[:8])

    # Direct feeds and X discovery supplement model-assisted search. Every URL
    # still goes through the same publisher, date and page verification below.
    if verify_pages:
        raw_items.extend(_discover_official_feed_items(subscription))

    # Direct discovery supplements model-assisted search for key OpenAI/Codex
    # accounts. Each URL still goes through the same oEmbed author/date check.
    raw_items.extend(_discover_direct_x_items(subscription))

    result = []
    seen = set()
    allowed_dates = {
        (current - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(lookback_days)
    }
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        url = _canonical_url(raw.get("url"))
        title = re.sub(r"\s+", " ", str(raw.get("title") or "")).strip()
        published_date = str(raw.get("published_date") or "")[:10]
        summary = re.sub(r"\s+", " ", str(raw.get("summary") or "")).strip()
        source_type = _item_source_type({**raw, "url": url}, subscription)
        if (
            not url
            or url in seen
            or not title
            or not summary
            or not source_type
        ):
            continue
        item = {
            "title": title,
            "publisher": str(raw.get("publisher") or "").strip(),
            "published_date": published_date,
            "url": url,
            "summary": summary[:320],
            "why_it_matters": re.sub(
                r"\s+", " ", str(raw.get("why_it_matters") or "")
            ).strip()[:220],
            "category": str(raw.get("category") or "").strip(),
            "entities": _normalize_names(list(raw.get("entities") or []), limit=8),
            "source_type": source_type,
            "verified": True,
        }
        if source_type == "官方 X" and verify_pages:
            verified_x = _verify_x_post(item, x_accounts)
            if not verified_x:
                print(f"X 原帖核验失败，跳过: {title} | {url}", flush=True)
                continue
            item = verified_x
            source_text = re.sub(
                r"\s+", " ", str(item.get("source_text") or "")
            ).strip()
            if source_text:
                item["summary"] = source_text[:320]
        elif verify_pages and not _page_is_accessible_and_consistent(item, source_type):
            print(f"资讯原文核验失败，跳过: {title} | {url}", flush=True)
            continue
        if item["published_date"] not in allowed_dates:
            continue
        seen.add(url)
        result.append(item)
    result.sort(key=lambda item: item.get("published_date", ""), reverse=True)
    return _deduplicate_events(result)[:10]


def _archive_document(year: int) -> dict | None:
    init_tech_news()
    with _connect() as conn:
        row = conn.execute(
            "SELECT document_id, url FROM news_archive_documents WHERE year=?",
            (year,),
        ).fetchone()
    return dict(row) if row else None


def archive_tech_news(items: list[dict], *, now: datetime | None = None) -> dict | None:
    if not items:
        return None
    from feishu_docs import (
        _heading_block,
        _request,
        _root_child_count,
        _text_run,
        get_document_url,
        set_public_readable,
    )
    from feishu_sender import get_token

    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    year = current.year
    token = get_token()
    existing = _archive_document(year)
    document_id = str(existing.get("document_id") or "") if existing else ""
    if not document_id:
        result = _request(
            "POST",
            "/docx/v1/documents",
            token,
            json={"title": f"AI 科技资讯库｜{year}"},
        )
        document_id = result["data"]["document"]["document_id"]
        _request(
            "POST",
            f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            token,
            json={
                "children": [
                    _heading_block(f"AI 科技资讯库｜{year}", level=1),
                    {
                        "block_type": 2,
                        "text": {
                            "elements": [
                                _text_run(
                                    "只归档能够核验为微信公众号原文、企业官方页面或官方 X 原帖的 AI 科技动态。"
                                )
                            ],
                            "style": {},
                        },
                    },
                ]
            },
        )

    rows = [["日期", "来源", "标题 / 原文", "事实摘要", "为什么值得关注", "涉及主体"]]
    for item in items:
        rows.append(
            [
                item["published_date"],
                f"{item['publisher']}\n{item['source_type']}",
                item["title"],
                item["summary"],
                item.get("why_it_matters", ""),
                "、".join(item.get("entities", [])),
            ]
        )
    table_id = f"table_{uuid.uuid4().hex}"
    cell_ids, descendants = [], []
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            cell_id = f"cell_{uuid.uuid4().hex}"
            text_id = f"text_{uuid.uuid4().hex}"
            cell_ids.append(cell_id)
            descendants.append(
                {
                    "block_id": cell_id,
                    "block_type": 32,
                    "table_cell": {},
                    "children": [text_id],
                }
            )
            style = {"bold": row_index == 0}
            if row_index > 0 and column_index == 2:
                style["link"] = {
                    "url": urllib.parse.quote(items[row_index - 1]["url"], safe="")
                }
            descendants.append(
                {
                    "block_id": text_id,
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {
                                "text_run": {
                                    "content": str(value),
                                    "text_element_style": style,
                                }
                            }
                        ],
                        "style": {},
                    },
                    "children": [],
                }
            )
    descendants.insert(
        0,
        {
            "block_id": table_id,
            "block_type": 31,
            "table": {
                "property": {
                    "row_size": len(rows),
                    "column_size": 6,
                    "column_width": [100, 145, 250, 280, 230, 150],
                }
            },
            "children": cell_ids,
        },
    )
    _request(
        "POST",
        f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
        token,
        json={"children": [_heading_block(f"{current:%Y-%m-%d}｜新增 {len(items)} 条", level=2)]},
    )
    _request(
        "POST",
        f"/docx/v1/documents/{document_id}/blocks/{document_id}/descendant",
        token,
        json={
            "children_id": [table_id],
            "descendants": descendants,
            "index": _root_child_count(document_id, token),
        },
    )
    set_public_readable(document_id, token)
    url = get_document_url(document_id, token)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO news_archive_documents (year, document_id, url, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(year) DO UPDATE SET
                document_id=excluded.document_id,
                url=excluded.url,
                updated_at=excluded.updated_at
            """,
            (year, document_id, url, current.isoformat(timespec="seconds")),
        )
    return {"document_id": document_id, "url": url}


def send_tech_news_digest(
    chat_id: str,
    items: list[dict],
    *,
    archive_url: str = "",
    now: datetime | None = None,
) -> None:
    from feishu_sender import get_token

    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    visible_items = items[:10]
    grouped: dict[str, list[dict]] = {
        category: [] for category in NEWS_CATEGORY_ORDER
    }
    for item in visible_items:
        grouped[_news_category(item)].append(item)
    active_categories = [
        category for category in NEWS_CATEGORY_ORDER if grouped[category]
    ]
    publisher_count = len(
        {
            str(item.get("publisher") or "").strip().casefold()
            for item in visible_items
            if str(item.get("publisher") or "").strip()
        }
    )
    elements = [
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "仅收录已核验的一手原文 · 跨来源去重 · 已发送内容不重复推送",
                }
            ],
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "**📌 今晚速览**\n"
                    f"{len(visible_items)} 条资讯 · {len(active_categories)} 类主题 "
                    f"· {publisher_count} 个官方来源\n"
                    "聚焦模型、产品、Agent、算力、具身、资本与治理。"
                ),
            },
        },
    ]
    display_index = 0
    for category_index, category in enumerate(active_categories):
        if category_index == 0:
            elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{NEWS_CATEGORY_ICONS[category]} {category}"
                        f"（{len(grouped[category])} 条）**"
                    ),
                },
            }
        )
        for item in grouped[category]:
            display_index += 1
            title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
            summary = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()
            why_it_matters = re.sub(
                r"\s+", " ", str(item.get("why_it_matters") or "")
            ).strip()
            # Feed pages occasionally expose image alt text as their summary.
            # It is better to point readers to the verified original than to
            # render a misleading screenshot description as news copy.
            looks_like_image_alt = bool(
                re.search(
                    r"\b(?:an?|the)\s+(?:illustrated\s+)?(?:image|screenshot|photo)\b"
                    r"|\b(?:image|screenshot)\s+(?:shows?|with|featuring)\b",
                    summary,
                    flags=re.I,
                )
            )
            if looks_like_image_alt and not re.search(r"[\u4e00-\u9fff]", summary):
                summary = "该页面未提供可靠的文字摘要，请点击标题查看官方原文。"
            summary = summary.replace("`", "")
            why_it_matters = why_it_matters.replace("`", "")
            published_date = str(item.get("published_date") or "")
            display_date = published_date[5:] if len(published_date) >= 10 else published_date
            content = (
                f"**{display_index:02d} · [{title}]({item['url']})**\n"
                f"{item['publisher']} · {item['source_type']} · {display_date}\n"
                f"{summary}"
            )
            if why_it_matters:
                content += f"\n💡 **关注点：**{why_it_matters}"
            elements.append(
                {"tag": "div", "text": {"tag": "lark_md", "content": content}}
            )
        if category_index < len(active_categories) - 1:
            elements.append({"tag": "hr"})
    if archive_url:
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "📚 查看资讯总库"},
                        "type": "primary",
                        "url": archive_url,
                    }
                ],
            }
        )
    card = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "template": "indigo",
            "title": {"tag": "plain_text", "content": "🌙 AI 科技情报 · 晚报"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"{current:%Y年%m月%d日} · {len(visible_items)} 条可信原文",
            },
        },
        "elements": elements,
    }
    response = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={
            "Authorization": f"Bearer {get_token()}",
            "Content-Type": "application/json",
        },
        json={
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code", 0) != 0:
        raise RuntimeError(f"飞书资讯晚报发送失败: {payload}")


def due_news_subscriptions(now: datetime | None = None) -> list[dict]:
    init_tech_news()
    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    today = current.strftime("%Y-%m-%d")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM news_subscriptions WHERE enabled=1"
        ).fetchall()
        completed = {
            row[0]
            for row in conn.execute(
                "SELECT chat_id FROM news_runs WHERE run_date=?", (today,)
            ).fetchall()
        }
    result = []
    for row in rows:
        value = dict(row)
        if value["chat_id"] in completed or value["push_time"] > current.strftime("%H:%M"):
            continue
        value["public_accounts"] = _normalize_names(
            json.loads(value["public_accounts"])
        )
        value["companies"] = _normalize_names(json.loads(value["companies"]))
        value["x_accounts"] = _normalize_x_handles(
            json.loads(value.get("x_accounts") or "[]")
        )
        value["enabled"] = True
        result.append(value)
    return result


def _delivered_urls(chat_id: str) -> set[str]:
    init_tech_news()
    with _connect() as conn:
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT url FROM news_deliveries WHERE chat_id=?", (chat_id,)
            ).fetchall()
        }


def _delivered_items(chat_id: str) -> list[dict]:
    """Load prior delivery metadata so the same event is not resent via a new URL."""
    init_tech_news()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT url, title, summary, publisher, entities_json
            FROM news_deliveries WHERE chat_id=?
            ORDER BY delivered_at DESC LIMIT 500
            """,
            (chat_id,),
        ).fetchall()
    result = []
    for row in rows:
        try:
            entities = json.loads(row["entities_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            entities = []
        result.append(
            {
                "url": str(row["url"] or ""),
                "title": str(row["title"] or ""),
                "summary": str(row["summary"] or ""),
                "publisher": str(row["publisher"] or ""),
                "entities": entities,
            }
        )
    return result


def _is_previously_delivered(item: dict, delivered_items: list[dict]) -> bool:
    url = str(item.get("url") or "")
    for delivered in delivered_items:
        if url and url == str(delivered.get("url") or ""):
            return True
        if delivered.get("title") and _same_event(item, delivered):
            return True
    return False


def _mark_news_run(chat_id: str, items: list[dict], now: datetime) -> None:
    init_tech_news()
    with _connect() as conn:
        for item in items:
            conn.execute(
                """
                INSERT OR IGNORE INTO news_deliveries
                (chat_id, url, delivered_at, title, summary, publisher, entities_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    item["url"],
                    now.isoformat(timespec="seconds"),
                    str(item.get("title") or ""),
                    str(item.get("summary") or ""),
                    str(item.get("publisher") or ""),
                    json.dumps(item.get("entities") or [], ensure_ascii=False),
                ),
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO news_runs (chat_id, run_date, completed_at)
            VALUES (?, ?, ?)
            """,
            (
                chat_id,
                now.strftime("%Y-%m-%d"),
                now.isoformat(timespec="seconds"),
            ),
        )


def dispatch_due_tech_news(now: datetime | None = None) -> int:
    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    total = 0
    for subscription in due_news_subscriptions(current):
        delivered = _delivered_items(subscription["chat_id"])
        items = [
            item
            for item in collect_tech_news(subscription, now=current)
            if not _is_previously_delivered(item, delivered)
        ]
        if not items:
            print(
                f"近 {NEWS_LOOKBACK_DAYS} 天无未发送可靠原文，回补近 90 天: "
                f"{subscription['chat_id']}",
                flush=True,
            )
            items = [
                item
                for item in collect_tech_news(
                    subscription, now=current, lookback_days=90
                )
                if not _is_previously_delivered(item, delivered)
            ]
        if not items:
            print(
                f"AI 科技晚报无新增可靠原文: {subscription['chat_id']}", flush=True
            )
            _mark_news_run(subscription["chat_id"], [], current)
            continue
        archive_url = ""
        try:
            document = archive_tech_news(items, now=current)
            archive_url = str(document.get("url") or "") if document else ""
        except Exception as exc:
            print(f"AI 科技资讯归档失败，继续发送晚报: {exc}", flush=True)
        send_tech_news_digest(
            subscription["chat_id"], items, archive_url=archive_url, now=current
        )
        _mark_news_run(subscription["chat_id"], items, current)
        total += len(items)
    return total
