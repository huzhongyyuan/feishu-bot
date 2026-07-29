import sqlite3
import os
from datetime import datetime


DB_PATH = "data/papers.db"


def get_conn():

    os.makedirs(
        "data",
        exist_ok=True
    )

    return sqlite3.connect(DB_PATH)



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



def save_paper(paper):

    conn = get_conn()

    cur = conn.cursor()

    try:

        cur.execute(
            """
            INSERT INTO papers
            (
            title,
            venue,
            summary,
            contributions,
            score,
            paper_url,
            code_url,
            push_time
            )
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                paper.get("title",""),
                paper.get("venue",""),
                paper.get("summary",""),
                "\n".join(
                    paper.get("contributions",[])
                ),
                paper.get("score",0),
                paper.get("paper_url",""),
                paper.get("code_url",""),
                datetime.now().strftime("%Y-%m-%d")
            )
        )

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
