import sqlite3
import os
import json
import re
from datetime import datetime


DB_PATH = "data/papers.db"


def get_conn():

    os.makedirs(
        "data",
        exist_ok=True
    )

    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.execute("PRAGMA busy_timeout=30000")
    return connection



def init_db():

    conn = get_conn()

    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE,
            venue TEXT,
            summary TEXT,
            contributions TEXT,
            score REAL,
            paper_url TEXT,
            code_url TEXT,
            push_time TEXT
        )
        """
    )

    existing_columns = {
        row[1] for row in cur.execute("PRAGMA table_info(papers)").fetchall()
    }
    extra_columns = {
        "summary_en": "TEXT",
        "abstract_zh": "TEXT",
        "bilingual_source": "TEXT",
        "arxiv_id": "TEXT",
        "authors": "TEXT",
        "institutions": "TEXT",
        "institutions_source": "TEXT",
        "contributions_original": "TEXT",
        "contributions_original_source": "TEXT",
        "abstract": "TEXT",
        "published": "TEXT",
        "categories": "TEXT",
        "source": "TEXT",
        "reason": "TEXT",
        "task": "TEXT",
        "main_method": "TEXT",
        "opinion": "TEXT",
        "week_start": "TEXT",
        "week_end": "TEXT",
        "feishu_doc_url": "TEXT",
        "pdf_url": "TEXT",
        "official_venue_url": "TEXT",
        "research_question": "TEXT",
        "background": "TEXT",
        "method_result_map": "TEXT",
        "key_results": "TEXT",
        "evidence_chain": "TEXT",
        "discussion_highlights": "TEXT",
        "limitations": "TEXT",
        "writing_notes": "TEXT",
        "core_insights": "TEXT",
        "figure_insights": "TEXT",
        "reading_guide": "TEXT",
        "deep_reading_source": "TEXT",
        "code_host": "TEXT",
        "repo_stars": "INTEGER",
        "repo_archived": "INTEGER",
        "open_source_verified": "INTEGER",
        "large_team_verified": "INTEGER",
        "team_evidence": "TEXT",
        "llm_open_source_verified": "INTEGER",
        "llm_open_source_evidence": "TEXT",
        "code_license_status": "TEXT",
        "official_source_code_verified": "INTEGER",
    }
    for column, column_type in extra_columns.items():
        if column not in existing_columns:
            cur.execute(f"ALTER TABLE papers ADD COLUMN {column} {column_type}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_deliveries (
            chat_id TEXT NOT NULL,
            title TEXT NOT NULL,
            delivered_at TEXT NOT NULL,
            PRIMARY KEY (chat_id, title)
        )
        """
    )

    conn.commit()
    conn.close()



def paper_exists(title):

    conn = get_conn()

    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM papers WHERE title=?",
        (title,)
    )

    result = cur.fetchone()

    conn.close()

    return result is not None


def paper_delivered(chat_id, title):
    init_db()
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM paper_deliveries WHERE chat_id=? AND title=?",
        (chat_id, title),
    ).fetchone()
    conn.close()
    return row is not None


def get_delivered_titles(chat_id):
    init_db()
    conn = get_conn()
    rows = conn.execute(
        "SELECT title FROM paper_deliveries WHERE chat_id=?",
        (chat_id,),
    ).fetchall()
    conn.close()
    return {str(row[0]) for row in rows if str(row[0]).strip()}


def save_delivery(chat_id, title):
    init_db()
    conn = get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO paper_deliveries (chat_id, title, delivered_at)
        VALUES (?, ?, ?)
        """,
        (chat_id, title, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()



def save_paper(paper):
    init_db()
    arxiv_id = str(paper.get("id") or paper.get("arxiv_id") or "").strip()
    if not arxiv_id:
        match = re.search(r"(\d{4}\.\d{4,5})", str(paper.get("paper_url") or ""))
        arxiv_id = match.group(1) if match else ""
    conn = get_conn()

    try:
        values = {
            "title": paper.get("title", ""),
            "venue": paper.get("venue", ""),
            "summary": paper.get("summary", ""),
            "summary_en": paper.get("summary_en", ""),
            "abstract_zh": paper.get("abstract_zh", ""),
            "bilingual_source": paper.get("bilingual_source", ""),
            "contributions": "\n".join(paper.get("contributions", [])),
            "score": paper.get("score", 0),
            "paper_url": paper.get("paper_url", ""),
            "code_url": paper.get("code_url", ""),
            "push_time": paper.get("push_time") or datetime.now().strftime("%Y-%m-%d"),
            "arxiv_id": arxiv_id,
            "authors": json.dumps(paper.get("authors", []), ensure_ascii=False),
            "institutions": json.dumps(paper.get("institutions", []), ensure_ascii=False),
            "institutions_source": paper.get("institutions_source", ""),
            "contributions_original": json.dumps(
                paper.get("contributions_original", []), ensure_ascii=False
            ),
            "contributions_original_source": paper.get("contributions_original_source", ""),
            "abstract": paper.get("abstract", ""),
            "published": paper.get("published", ""),
            "categories": json.dumps(paper.get("categories", []), ensure_ascii=False),
            "source": paper.get("source", "arXiv"),
            "reason": paper.get("reason", ""),
            "task": paper.get("task", ""),
            "main_method": paper.get("main_method", ""),
            "opinion": paper.get("opinion", ""),
            "week_start": paper.get("week_start", ""),
            "week_end": paper.get("week_end", ""),
            "feishu_doc_url": paper.get("feishu_doc_url", ""),
            "pdf_url": paper.get("pdf_url", ""),
            "official_venue_url": paper.get("official_venue_url", ""),
            "research_question": json.dumps(
                paper.get("research_question", {}), ensure_ascii=False
            ),
            "background": json.dumps(paper.get("background", []), ensure_ascii=False),
            "method_result_map": json.dumps(
                paper.get("method_result_map", []), ensure_ascii=False
            ),
            "key_results": json.dumps(paper.get("key_results", []), ensure_ascii=False),
            "evidence_chain": json.dumps(
                paper.get("evidence_chain", []), ensure_ascii=False
            ),
            "discussion_highlights": json.dumps(
                paper.get("discussion_highlights", []), ensure_ascii=False
            ),
            "limitations": json.dumps(paper.get("limitations", []), ensure_ascii=False),
            "writing_notes": json.dumps(
                paper.get("writing_notes", []), ensure_ascii=False
            ),
            "core_insights": json.dumps(
                paper.get("core_insights", []), ensure_ascii=False
            ),
            "figure_insights": json.dumps(
                paper.get("figure_insights", []), ensure_ascii=False
            ),
            "reading_guide": json.dumps(
                paper.get("reading_guide", []), ensure_ascii=False
            ),
            "deep_reading_source": paper.get("deep_reading_source", ""),
            "code_host": paper.get("code_host", ""),
            "repo_stars": int(paper.get("repo_stars") or 0),
            "repo_archived": int(bool(paper.get("repo_archived"))),
            "open_source_verified": int(bool(paper.get("open_source_verified"))),
            "large_team_verified": int(bool(paper.get("large_team_verified"))),
            "team_evidence": paper.get("team_evidence", ""),
            "llm_open_source_verified": int(
                bool(paper.get("llm_open_source_verified"))
            ),
            "llm_open_source_evidence": paper.get(
                "llm_open_source_evidence", ""
            ),
            "code_license_status": paper.get("code_license_status", ""),
            "official_source_code_verified": int(
                bool(paper.get("official_source_code_verified"))
            ),
        }
        columns = list(values)
        placeholders = ",".join("?" for _ in columns)
        updates = ",\n                ".join(
            f"{column}=excluded.{column}" for column in columns if column != "title"
        )
        sql = f"""
            INSERT INTO papers ({','.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(title) DO UPDATE SET
                {updates}
        """
        conn.execute(sql, tuple(values[column] for column in columns))

        conn.commit()

    except sqlite3.IntegrityError:
        pass

    conn.close()



def get_recent_papers(limit=10):

    conn=get_conn()

    cur=conn.cursor()

    cur.execute(
        """
        SELECT
        title,
        venue,
        score,
        paper_url,
        push_time
        FROM papers
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    )

    rows=cur.fetchall()

    conn.close()

    return rows



if __name__=="__main__":
    init_db()
    print("database initialized")
