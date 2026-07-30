import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("EVENT_DB_PATH", BASE_DIR / "data" / "events.db"))
EVENT_RETENTION_DAYS = int(os.getenv("EVENT_RETENTION_DAYS", "30"))


def init_event_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            DELETE FROM processed_events
            WHERE created_at < datetime('now', ?)
            """,
            (f"-{EVENT_RETENTION_DAYS} days",),
        )
        conn.commit()


def seen_or_save(event_id):
    if not event_id:
        return False

    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO processed_events(event_id)
            VALUES (?)
            """,
            (event_id,),
        )
        conn.commit()

        return cursor.rowcount == 0
