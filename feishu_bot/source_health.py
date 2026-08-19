"""Durable health metrics for scheduled paper discovery sources."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar


DB_PATH = Path(__file__).resolve().parent / "data" / "source_health.db"
T = TypeVar("T")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_health (
            source TEXT PRIMARY KEY,
            last_attempt_at TEXT NOT NULL,
            last_success_at TEXT NOT NULL DEFAULT '',
            ok INTEGER NOT NULL,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    return conn


def track_source(source: str, fetch: Callable[[], T], require_nonempty: bool = False) -> T:
    started = time.monotonic()
    attempted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        result = fetch()
        if require_nonempty and hasattr(result, "__len__") and len(result) == 0:
            raise RuntimeError("source returned no candidates")
    except Exception as exc:
        latency = round((time.monotonic() - started) * 1000)
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO source_health
                    (source, last_attempt_at, ok, latency_ms, consecutive_failures, last_error)
                VALUES (?, ?, 0, ?, 1, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_attempt_at=excluded.last_attempt_at,
                    ok=0,
                    latency_ms=excluded.latency_ms,
                    consecutive_failures=source_health.consecutive_failures+1,
                    last_error=excluded.last_error
                """,
                (source, attempted_at, latency, str(exc)[:1000]),
            )
        raise
    latency = round((time.monotonic() - started) * 1000)
    count = len(result) if hasattr(result, "__len__") else 0
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO source_health
                (source, last_attempt_at, last_success_at, ok, candidate_count, latency_ms)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                last_attempt_at=excluded.last_attempt_at,
                last_success_at=excluded.last_success_at,
                ok=1,
                candidate_count=excluded.candidate_count,
                latency_ms=excluded.latency_ms,
                consecutive_failures=0,
                last_error=''
            """,
            (source, attempted_at, attempted_at, count, latency),
        )
    return result


def health_snapshot() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM source_health ORDER BY source"
        ).fetchall()
    return [dict(row) | {"ok": bool(row["ok"])} for row in rows]
