import os
import sqlite3

DB_PATH = "data/events.db"


def init_event_db():
    os.makedirs("data", exist_ok=True)

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
