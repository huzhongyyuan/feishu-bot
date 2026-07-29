import sqlite3
import os


DB="data/papers.db"


def init():

    os.makedirs(
        "data",
        exist_ok=True
    )

    conn=sqlite3.connect(DB)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS paper_cache(
        title TEXT PRIMARY KEY,
        url TEXT,
        content TEXT
    )
    """)

    conn.commit()
    conn.close()



def get(title):

    conn=sqlite3.connect(DB)

    r=conn.execute(
        "select content from paper_cache where title=?",
        (title,)
    ).fetchone()

    conn.close()

    return r[0] if r else None



def save(title,url,content):

    conn=sqlite3.connect(DB)

    conn.execute(
        """
        insert or replace into paper_cache
        values(?,?,?)
        """,
        (
            title,
            url,
            content
        )
    )

    conn.commit()
    conn.close()
