from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DB_PATH = Path(__file__).resolve().parent / "data" / "chat_memory.db"
SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_CONTEXT_TURNS = 6
MAX_STORED_TURNS_PER_CHAT = 60
MAX_USER_CHARS = 2000
MAX_ASSISTANT_CHARS = 4000
MAX_CONTEXT_CHARS = 9000


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_chat_memory() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_profiles (
                chat_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                instructions TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        profile_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(chat_profiles)").fetchall()
        }
        if "preferred_provider" not in profile_columns:
            conn.execute(
                "ALTER TABLE chat_profiles "
                "ADD COLUMN preferred_provider TEXT NOT NULL DEFAULT 'auto'"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                user_text TEXT NOT NULL,
                assistant_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_turns_chat_id_id "
            "ON chat_turns(chat_id, id DESC)"
        )


def set_chat_profile(
    chat_id: str,
    name: str,
    instructions: str,
    preferred_provider: str = "auto",
) -> None:
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        raise ValueError("chat_id 不能为空")
    init_chat_memory()
    now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_profiles
            (chat_id, name, instructions, preferred_provider, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                name=excluded.name,
                instructions=excluded.instructions,
                preferred_provider=excluded.preferred_provider,
                updated_at=excluded.updated_at
            """,
            (
                chat_id,
                str(name).strip(),
                str(instructions).strip(),
                str(preferred_provider or "auto").strip().casefold(),
                now,
            ),
        )


def get_chat_profile(chat_id: str) -> dict | None:
    if not str(chat_id or "").strip():
        return None
    init_chat_memory()
    with _connect() as conn:
        row = conn.execute(
            "SELECT chat_id, name, instructions, preferred_provider "
            "FROM chat_profiles WHERE chat_id=?",
            (chat_id,),
        ).fetchone()
    return dict(row) if row else None


def preferred_chat_provider(chat_id: str, default: str = "auto") -> str:
    profile = get_chat_profile(chat_id)
    provider = str(
        (profile or {}).get("preferred_provider") or default or "auto"
    ).strip().casefold()
    return provider if provider in {"auto", "glm", "yuanbao", "both"} else "auto"


def remember_chat_turn(chat_id: str, user_text: str, assistant_text: str) -> None:
    chat_id = str(chat_id or "").strip()
    user_text = str(user_text or "").strip()[:MAX_USER_CHARS]
    assistant_text = str(assistant_text or "").strip()[:MAX_ASSISTANT_CHARS]
    if not chat_id or not user_text or not assistant_text:
        return
    init_chat_memory()
    now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_turns (chat_id, user_text, assistant_text, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, user_text, assistant_text, now),
        )
        conn.execute(
            """
            DELETE FROM chat_turns
            WHERE chat_id=? AND id NOT IN (
                SELECT id FROM chat_turns
                WHERE chat_id=? ORDER BY id DESC LIMIT ?
            )
            """,
            (chat_id, chat_id, MAX_STORED_TURNS_PER_CHAT),
        )


def recent_chat_turns(chat_id: str, limit: int | None = None) -> list[dict]:
    if not str(chat_id or "").strip():
        return []
    init_chat_memory()
    context_turns = max(
        1,
        min(
            int(limit or os.getenv("CHAT_MEMORY_CONTEXT_TURNS", DEFAULT_CONTEXT_TURNS)),
            12,
        ),
    )
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT user_text, assistant_text, created_at
            FROM chat_turns WHERE chat_id=?
            ORDER BY id DESC LIMIT ?
            """,
            (chat_id, context_turns),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def build_memory_prompt(chat_id: str, question: str) -> str:
    """Inject only the current chat's profile and recent turns."""
    question = str(question or "").strip()
    if not chat_id:
        return question
    profile = get_chat_profile(chat_id)
    turns = recent_chat_turns(chat_id)
    if not profile and not turns:
        return question

    sections = [
        "你正在处理一个有独立记忆的飞书群对话。",
        "只能使用下面当前群的资料；不得推断、引用或泄露其他群的对话。",
    ]
    if profile:
        sections.append(
            f"当前群：{profile['name']}\n群角色：{profile['instructions']}"
        )
    if turns:
        history = []
        for turn in turns:
            history.append(
                f"用户：{turn['user_text']}\n助手：{turn['assistant_text']}"
            )
        history_text = "\n\n".join(history)
        if len(history_text) > MAX_CONTEXT_CHARS:
            history_text = history_text[-MAX_CONTEXT_CHARS:]
        sections.append("当前群最近对话：\n" + history_text)
    sections.append("当前问题：\n" + question)
    sections.append("请直接回答当前问题；历史内容仅用于延续语境，不能当作可靠事实来源。")
    return "\n\n".join(sections)
