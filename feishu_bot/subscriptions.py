from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


DB_PATH = Path(__file__).resolve().parent / "data" / "subscriptions.db"
DEFAULT_TOPICS = [
    "数字人",
    "Motion Generation",
    "具身智能",
    "世界模型",
    "视频生成",
    "人体动作",
    "全景相机",
    "全景视频",
]
DEFAULT_PUSH_TIMES = ["08:00", "20:00"]
DEFAULT_WEEKLY_PUSH_WEEKDAY = 0  # Monday
DEFAULT_WEEKLY_PUSH_TIME = "09:00"
WEEKLY_RETRY_HOURS = 6
DAILY_RETRY_MINUTES = 60
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_subscriptions() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                chat_id TEXT PRIMARY KEY,
                topics TEXT NOT NULL,
                push_time TEXT NOT NULL DEFAULT '08:00',
                weekdays_only INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_push_date TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_subscription_runs (
                chat_id TEXT NOT NULL,
                week_start TEXT NOT NULL,
                status TEXT NOT NULL,
                attempted_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (chat_id, week_start)
            )
            """
        )
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(subscriptions)")
        }
        if "push_times" not in columns:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN push_times TEXT")
        conn.execute(
            """
            UPDATE subscriptions
            SET push_times=json_array(push_time)
            WHERE push_times IS NULL OR push_times=''
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscription_runs (
                chat_id TEXT NOT NULL,
                run_date TEXT NOT NULL,
                push_time TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, run_date, push_time)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_subscription_attempts (
                chat_id TEXT NOT NULL,
                run_date TEXT NOT NULL,
                push_time TEXT NOT NULL,
                attempted_at TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (chat_id, run_date, push_time)
            )
            """
        )


def _normalize_push_times(values: list[str]) -> list[str]:
    result = set()
    for value in values:
        match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value))
        if not match:
            raise ValueError("推送时间格式不正确")
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError("推送时间格式不正确")
        result.add(f"{hour:02d}:{minute:02d}")
    if not result:
        raise ValueError("至少需要一个推送时间")
    return sorted(result)


def _normalize_topics(values: list[str]) -> list[str]:
    topics = []
    seen = set()
    for value in values:
        topic = re.sub(r"\s+", " ", value).strip(" ，、,;；")
        if not topic or len(topic) > 40 or topic in seen:
            continue
        seen.add(topic)
        topics.append(topic)
    return topics[:10]


def get_subscription(chat_id: str, create: bool = True) -> dict | None:
    init_subscriptions()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE chat_id=?",
            (chat_id,),
        ).fetchone()
        if row is None and create:
            now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
            conn.execute(
                """
                INSERT INTO subscriptions
                (chat_id, topics, push_time, push_times, weekdays_only, enabled, updated_at)
                VALUES (?, ?, ?, ?, 0, 1, ?)
                """,
                (
                    chat_id,
                    json.dumps(DEFAULT_TOPICS, ensure_ascii=False),
                    DEFAULT_PUSH_TIMES[0],
                    json.dumps(DEFAULT_PUSH_TIMES),
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["topics"] = json.loads(result["topics"])
    try:
        result["push_times"] = _normalize_push_times(
            json.loads(result.get("push_times") or "[]")
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        result["push_times"] = [result["push_time"]]
    result["enabled"] = bool(result["enabled"])
    result["weekdays_only"] = bool(result["weekdays_only"])
    return result


def update_subscription(chat_id: str, **changes) -> dict:
    get_subscription(chat_id, create=True)
    allowed = {
        "topics", "push_time", "push_times", "weekdays_only", "enabled",
        "last_push_date",
    }
    updates = {key: value for key, value in changes.items() if key in allowed}
    if "topics" in updates:
        updates["topics"] = json.dumps(
            _normalize_topics(list(updates["topics"])), ensure_ascii=False
        )
    for key in ("weekdays_only", "enabled"):
        if key in updates:
            updates[key] = int(bool(updates[key]))
    if "push_times" in updates:
        push_times = _normalize_push_times(list(updates["push_times"]))
        updates["push_times"] = json.dumps(push_times)
        updates["push_time"] = push_times[0]
    elif "push_time" in updates:
        push_times = _normalize_push_times([updates["push_time"]])
        updates["push_time"] = push_times[0]
        updates["push_times"] = json.dumps(push_times)
    updates["updated_at"] = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    assignments = ", ".join(f"{key}=?" for key in updates)
    values = list(updates.values()) + [chat_id]
    with _connect() as conn:
        conn.execute(
            f"UPDATE subscriptions SET {assignments} WHERE chat_id=?",
            values,
        )
    return get_subscription(chat_id, create=False)


def format_subscription(subscription: dict) -> str:
    status = "已启用" if subscription["enabled"] else "已暂停"
    days = "仅工作日" if subscription["weekdays_only"] else "每天"
    topics = "、".join(subscription["topics"]) or "尚未设置"
    return (
        "📚 论文推送订阅\n\n"
        f"状态：{status}\n"
        f"主题：{topics}\n"
        f"时间：{'、'.join(subscription['push_times'])}（北京时间）\n"
        f"日期：{days}"
    )


def handle_subscription_command(chat_id: str, text: str) -> str | None:
    command = text.strip()

    match = re.fullmatch(r"订阅[：:\s]+(.+)", command)
    if match:
        topics = _normalize_topics(re.split(r"[，,、;；]+", match.group(1)))
        if not topics:
            return "请至少填写一个订阅主题，例如：订阅 世界模型、视频生成"
        subscription = update_subscription(chat_id, topics=topics, enabled=True)
        return "订阅主题已更新。\n\n" + format_subscription(subscription)

    match = re.fullmatch(r"推送时间[：:\s]+(.+)", command)
    if match:
        raw_times = re.split(r"[，,、;；\s]+", match.group(1).strip())
        try:
            push_times = _normalize_push_times(raw_times)
        except ValueError:
            return "推送时间格式不正确，请使用 00:00 到 23:59。"
        subscription = update_subscription(
            chat_id,
            push_times=push_times,
            enabled=True,
        )
        return "推送时间已更新。\n\n" + format_subscription(subscription)

    if command == "工作日推送":
        subscription = update_subscription(chat_id, weekdays_only=True, enabled=True)
        return "已改为仅工作日推送。\n\n" + format_subscription(subscription)

    if command in {"每天推送", "每日推送"}:
        subscription = update_subscription(chat_id, weekdays_only=False, enabled=True)
        return "已改为每天推送。\n\n" + format_subscription(subscription)

    if command in {"暂停论文推送", "取消订阅"}:
        subscription = update_subscription(chat_id, enabled=False)
        return "论文推送已暂停。\n\n" + format_subscription(subscription)

    if command in {"恢复论文推送", "开启论文推送"}:
        subscription = update_subscription(chat_id, enabled=True)
        return "论文推送已恢复。\n\n" + format_subscription(subscription)

    if command == "查看订阅":
        return format_subscription(get_subscription(chat_id, create=True))

    return None


def ensure_default_subscription() -> None:
    chat_id = os.getenv("FEISHU_CHAT_ID", "").strip()
    if chat_id:
        get_subscription(chat_id, create=True)


def due_subscriptions(now: datetime | None = None) -> list[dict]:
    init_subscriptions()
    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    today = current.strftime("%Y-%m-%d")
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE enabled=1
            """,
        ).fetchall()
        completed = {
            (row["chat_id"], row["push_time"])
            for row in conn.execute(
                "SELECT chat_id, push_time FROM subscription_runs WHERE run_date=?",
                (today,),
            ).fetchall()
        }
        attempts = {
            (row["chat_id"], row["push_time"]): dict(row)
            for row in conn.execute(
                "SELECT * FROM daily_subscription_attempts WHERE run_date=?",
                (today,),
            ).fetchall()
        }
    result = []
    for row in rows:
        item = dict(row)
        if item["weekdays_only"] and current.weekday() >= 5:
            continue
        try:
            push_times = _normalize_push_times(
                json.loads(item.get("push_times") or "[]")
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            push_times = [item["push_time"]]
        for push_time in push_times:
            if push_time > current.strftime("%H:%M"):
                continue
            if (item["chat_id"], push_time) in completed:
                continue
            attempt = attempts.get((item["chat_id"], push_time))
            if attempt and attempt.get("attempted_at"):
                try:
                    attempted_at = datetime.fromisoformat(attempt["attempted_at"])
                except ValueError:
                    attempted_at = None
                if attempted_at and current - attempted_at < timedelta(
                    minutes=DAILY_RETRY_MINUTES
                ):
                    continue
            due = dict(item)
            due["topics"] = json.loads(due["topics"])
            due["push_times"] = push_times
            due["due_push_time"] = push_time
            due["enabled"] = bool(due["enabled"])
            due["weekdays_only"] = bool(due["weekdays_only"])
            result.append(due)
    return result


def mark_pushed(
    chat_id: str,
    date_value: str | None = None,
    push_time: str | None = None,
) -> None:
    init_subscriptions()
    value = date_value or datetime.now(SHANGHAI).strftime("%Y-%m-%d")
    if push_time:
        push_time = _normalize_push_times([push_time])[0]
        with _connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO subscription_runs
                (chat_id, run_date, push_time, completed_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    chat_id,
                    value,
                    push_time,
                    datetime.now(SHANGHAI).isoformat(timespec="seconds"),
                ),
            )
            conn.execute(
                """
                DELETE FROM daily_subscription_attempts
                WHERE chat_id=? AND run_date=? AND push_time=?
                """,
                (chat_id, value, push_time),
            )
    update_subscription(chat_id, last_push_date=value)


def mark_daily_attempt(
    chat_id: str,
    push_time: str,
    date_value: str | None = None,
) -> None:
    init_subscriptions()
    run_date = date_value or datetime.now(SHANGHAI).strftime("%Y-%m-%d")
    normalized_time = _normalize_push_times([push_time])[0]
    now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO daily_subscription_attempts
            (chat_id, run_date, push_time, attempted_at, error)
            VALUES (?, ?, ?, ?, '')
            ON CONFLICT(chat_id, run_date, push_time) DO UPDATE SET
                attempted_at=excluded.attempted_at, error=''
            """,
            (chat_id, run_date, normalized_time, now),
        )


def mark_daily_failed(
    chat_id: str,
    push_time: str,
    error: str,
    date_value: str | None = None,
) -> None:
    init_subscriptions()
    run_date = date_value or datetime.now(SHANGHAI).strftime("%Y-%m-%d")
    normalized_time = _normalize_push_times([push_time])[0]
    with _connect() as conn:
        conn.execute(
            """
            UPDATE daily_subscription_attempts
            SET error=?
            WHERE chat_id=? AND run_date=? AND push_time=?
            """,
            (str(error)[:1000], chat_id, run_date, normalized_time),
        )


def due_weekly_subscriptions(
    now: datetime | None = None,
    weekday: int | None = None,
    push_time: str | None = None,
) -> list[dict]:
    """Return enabled chats due for one weekly roundup, with six-hour retry backoff."""
    init_subscriptions()
    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    configured_weekday = (
        int(os.getenv("WEEKLY_PUSH_WEEKDAY", DEFAULT_WEEKLY_PUSH_WEEKDAY))
        if weekday is None
        else int(weekday)
    )
    configured_weekday = max(0, min(6, configured_weekday))
    configured_time = _normalize_push_times(
        [push_time or os.getenv("WEEKLY_PUSH_TIME", DEFAULT_WEEKLY_PUSH_TIME)]
    )[0]
    if current.weekday() < configured_weekday:
        return []
    if (
        current.weekday() == configured_weekday
        and current.strftime("%H:%M") < configured_time
    ):
        return []

    monday = (current - timedelta(days=current.weekday())).date().isoformat()
    hour, minute = (int(value) for value in configured_time.split(":"))
    first_attempt_at = (current - timedelta(days=current.weekday())).replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    ) + timedelta(days=configured_weekday)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM subscriptions WHERE enabled=1"
        ).fetchall()
        runs = {
            row["chat_id"]: dict(row)
            for row in conn.execute(
                "SELECT * FROM weekly_subscription_runs WHERE week_start=?",
                (monday,),
            ).fetchall()
        }

    due = []
    for row in rows:
        run = runs.get(row["chat_id"])
        # A newly deployed scheduler must not backfill an old weekly report days
        # later. Existing failed runs may keep retrying, but the first attempt is
        # limited to a 24-hour window from the configured weekly time.
        if run is None and current > first_attempt_at + timedelta(hours=24):
            continue
        if run and run.get("status") == "completed":
            continue
        if run and run.get("attempted_at"):
            try:
                attempted_at = datetime.fromisoformat(run["attempted_at"])
            except ValueError:
                attempted_at = None
            if attempted_at and current - attempted_at < timedelta(
                hours=WEEKLY_RETRY_HOURS
            ):
                continue
        item = dict(row)
        item["topics"] = json.loads(item["topics"])
        item["weekly_run_key"] = monday
        item["weekly_push_time"] = configured_time
        due.append(item)
    return due


def mark_weekly_attempt(chat_id: str, week_start: str) -> None:
    init_subscriptions()
    now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO weekly_subscription_runs
            (chat_id, week_start, status, attempted_at, completed_at, error)
            VALUES (?, ?, 'running', ?, '', '')
            ON CONFLICT(chat_id, week_start) DO UPDATE SET
                status='running', attempted_at=excluded.attempted_at, error=''
            """,
            (chat_id, week_start, now),
        )


def mark_weekly_completed(chat_id: str, week_start: str) -> None:
    init_subscriptions()
    now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            UPDATE weekly_subscription_runs
            SET status='completed', completed_at=?, error=''
            WHERE chat_id=? AND week_start=?
            """,
            (now, chat_id, week_start),
        )


def mark_weekly_failed(chat_id: str, week_start: str, error: str) -> None:
    init_subscriptions()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE weekly_subscription_runs
            SET status='failed', error=?
            WHERE chat_id=? AND week_start=?
            """,
            (str(error)[:1000], chat_id, week_start),
        )
