from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import urllib.parse
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from glm_client import call_glm


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
    "NVIDIA",
    "OpenAI",
    "Anthropic/Claude",
    "阿里/Qwen",
    "字节/豆包",
    "腾讯/混元",
    "Google DeepMind",
    "Meta AI",
    "Microsoft AI",
    "xAI",
]
OFFICIAL_X_ACCOUNTS = {
    "OpenAI": ["OpenAI", "OpenAIDevs"],
    "Anthropic/Claude": ["AnthropicAI"],
    "NVIDIA": ["nvidia"],
    "阿里/Qwen": ["Alibaba_Qwen"],
    "腾讯/混元": ["TencentGlobal"],
    "Google DeepMind": ["GoogleDeepMind"],
    "Meta AI": ["AIatMeta"],
    "Microsoft AI": ["MSFTResearch", "Microsoft"],
    "xAI": ["spacexai", "grok"],
}
DEFAULT_X_ACCOUNTS = list(
    dict.fromkeys(
        handle
        for handles in OFFICIAL_X_ACCOUNTS.values()
        for handle in handles
    )
)
X_HANDLE_TO_COMPANY = {
    handle.casefold(): company
    for company, handles in OFFICIAL_X_ACCOUNTS.items()
    for handle in handles
}
COMPANY_DOMAINS = {
    "Moonshot/Kimi": {"moonshot.cn", "kimi.com"},
    "NVIDIA": {"nvidia.com"},
    "OpenAI": {"openai.com"},
    "Anthropic/Claude": {"anthropic.com", "claude.com"},
    "阿里/Qwen": {"alibaba.com", "aliyun.com", "alibabacloud.com", "qwen.ai"},
    "字节/豆包": {"bytedance.com", "volcengine.com", "doubao.com"},
    "腾讯/混元": {"tencent.com", "cloud.tencent.com"},
    "Google DeepMind": {"deepmind.google", "blog.google", "googleblog.com"},
    "Meta AI": {"ai.meta.com", "about.fb.com", "meta.com"},
    "Microsoft AI": {"microsoft.com"},
    "xAI": {"x.ai"},
}


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
                PRIMARY KEY (chat_id, url)
            )
            """
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
    chat_id = os.getenv("FEISHU_CHAT_ID", "").strip()
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
    result = json.loads(text)
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
) -> list[dict]:
    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    today = current.strftime("%Y-%m-%d")
    start_date = (current - timedelta(days=NEWS_LOOKBACK_DAYS - 1)).strftime(
        "%Y-%m-%d"
    )
    accounts = subscription["public_accounts"]
    companies = subscription["companies"]
    x_accounts = subscription.get("x_accounts", [])
    batches = [
        (accounts[index : index + 3], [], [])
        for index in range(0, len(accounts), 3)
    ] + [
        ([], companies[index : index + 4], [])
        for index in range(0, len(companies), 4)
    ] + [
        ([], [], x_accounts[index : index + 4])
        for index in range(0, len(x_accounts), 4)
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
  "entities":["涉及企业或模型"]
}}]}}
请分别检索本批每个来源，最多返回 5 条；宁可少报，不要猜测。
"""
        search_prompt = (
            f"分别检索这些公众号 {batch_accounts}、科技企业 {batch_companies} "
            f"和官方 X 账号 {batch_x_accounts} "
            f"最近 {NEWS_LOOKBACK_DAYS} 天的 AI 原文。优先 mp.weixin.qq.com 原文以及企业官网 "
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

    result = []
    seen = set()
    allowed_dates = {
        (current - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(NEWS_LOOKBACK_DAYS)
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
        elif verify_pages and not _page_is_accessible_and_consistent(item, source_type):
            print(f"资讯原文核验失败，跳过: {title} | {url}", flush=True)
            continue
        if item["published_date"] not in allowed_dates:
            continue
        seen.add(url)
        result.append(item)
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
    elements = [
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "✅ 仅收录已核验的公众号原文、企业官网或官方 X 原帖；同一事件跨来源去重",
                }
            ],
        }
    ]
    for index, item in enumerate(items[:10], start=1):
        entities = "、".join(item.get("entities", []))
        content = (
            f"**{index}. [{item['title']}]({item['url']})**\n"
            f"`{item['source_type']}`　{item['publisher']}　{item['published_date']}\n\n"
            f"{item['summary']}"
        )
        if item.get("why_it_matters"):
            content += f"\n\n💡 **关注价值**：{item['why_it_matters']}"
        if entities:
            content += f"\n\n🏷 {entities}"
        elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": content}}
        )
        if index < len(items[:10]):
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
            "template": "turquoise",
            "title": {"tag": "plain_text", "content": "AI 科技情报晚报"},
            "subtitle": {
                "tag": "plain_text",
                "content": f"{current:%Y-%m-%d} · 公众号 + 企业官网 + 官方 X",
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


def _mark_news_run(chat_id: str, items: list[dict], now: datetime) -> None:
    with _connect() as conn:
        for item in items:
            conn.execute(
                """
                INSERT OR IGNORE INTO news_deliveries (chat_id, url, delivered_at)
                VALUES (?, ?, ?)
                """,
                (chat_id, item["url"], now.isoformat(timespec="seconds")),
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
        delivered = _delivered_urls(subscription["chat_id"])
        items = [
            item
            for item in collect_tech_news(subscription, now=current)
            if item["url"] not in delivered
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
