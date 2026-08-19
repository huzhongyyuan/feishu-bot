"""Persistent retry queue for papers discovered by scheduled sources."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "data" / "paper_candidates.db"
MAX_ATTEMPTS = 6
RETENTION_DAYS = 14


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candidates (
            identity TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            next_retry_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    return conn


def candidate_identity(paper: dict) -> str:
    arxiv_id = str(paper.get("id") or paper.get("arxiv_id") or "").strip()
    if arxiv_id:
        return f"arxiv:{arxiv_id.casefold()}"
    url = str(paper.get("paper_url") or paper.get("url") or "").strip()
    if url:
        return f"url:{url.casefold().rstrip('/')}"
    title = re.sub(r"[^a-z0-9]+", "", str(paper.get("title") or "").casefold())
    return f"title:{title}" if title else ""


def store_candidates(papers: list[dict]) -> int:
    """Save every discovered item before expensive verification begins."""
    now = _now().isoformat(timespec="seconds")
    saved = 0
    with _connect() as conn:
        for paper in papers:
            identity = candidate_identity(paper)
            title = str(paper.get("title") or "").strip()
            if not identity or not title:
                continue
            existing = conn.execute(
                "SELECT payload, status FROM candidates WHERE identity=?", (identity,)
            ).fetchone()
            payload = dict(paper)
            if existing:
                try:
                    previous = json.loads(existing["payload"])
                except (TypeError, json.JSONDecodeError):
                    previous = {}
                previous.update({key: value for key, value in payload.items() if value not in (None, "", [])})
                payload = previous
            conn.execute(
                """
                INSERT INTO candidates
                    (identity, title, source, payload, status, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(identity) DO UPDATE SET
                    title=excluded.title,
                    source=excluded.source,
                    payload=excluded.payload,
                    last_seen_at=excluded.last_seen_at,
                    status=CASE
                        WHEN candidates.status='delivered' THEN 'delivered'
                        WHEN candidates.status='verified' THEN 'verified'
                        WHEN excluded.payload!=candidates.payload THEN 'pending'
                        ELSE candidates.status
                    END,
                    attempts=CASE
                        WHEN candidates.status NOT IN ('delivered', 'verified')
                             AND excluded.payload!=candidates.payload THEN 0
                        ELSE candidates.attempts
                    END,
                    next_retry_at=CASE
                        WHEN candidates.status NOT IN ('delivered', 'verified')
                             AND excluded.payload!=candidates.payload THEN ''
                        ELSE candidates.next_retry_at
                    END
                """,
                (
                    identity,
                    title,
                    str(paper.get("source") or "unknown"),
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            saved += 1
    return saved


def eligible_candidates(limit: int = 60) -> list[dict]:
    """Return due candidates, including prior transient failures."""
    now = _now()
    cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM candidates
            WHERE status!='delivered'
              AND attempts < ?
              AND last_seen_at >= ?
              AND (next_retry_at='' OR next_retry_at<=?)
            ORDER BY
              CASE status WHEN 'verified' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
              last_seen_at DESC
            LIMIT ?
            """,
            (MAX_ATTEMPTS, cutoff, now.isoformat(timespec="seconds"), int(limit)),
        ).fetchall()
    result = []
    for row in rows:
        try:
            result.append(json.loads(row["payload"]))
        except (TypeError, json.JSONDecodeError):
            continue
    return result


def mark_candidates(papers: list[dict], status: str, error: str = "") -> None:
    if status not in {"pending", "deferred", "verified", "delivered"}:
        raise ValueError(f"unsupported candidate status: {status}")
    now = _now()
    with _connect() as conn:
        for paper in papers:
            identity = candidate_identity(paper)
            if not identity:
                continue
            if status == "deferred":
                row = conn.execute(
                    "SELECT attempts FROM candidates WHERE identity=?", (identity,)
                ).fetchone()
                attempts = int(row["attempts"] if row else 0) + 1
                delay_hours = min(24 * 3, 6 * (2 ** min(attempts - 1, 4)))
                next_retry = (now + timedelta(hours=delay_hours)).isoformat(timespec="seconds")
                conn.execute(
                    """
                    UPDATE candidates
                    SET status='deferred', attempts=?, next_retry_at=?, last_error=?
                    WHERE identity=?
                    """,
                    (attempts, next_retry, str(error)[:1000], identity),
                )
            else:
                conn.execute(
                    """
                    UPDATE candidates
                    SET status=?, next_retry_at='', last_error=?
                    WHERE identity=?
                    """,
                    (status, str(error)[:1000], identity),
                )


def pool_summary() -> dict:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM candidates GROUP BY status"
        ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}
