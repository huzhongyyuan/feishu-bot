import sqlite3
import os


DB="data/events.db"


def init_event_db():

    os.makedirs(
        "data",
        exist_ok=True
    )

    conn=sqlite3.connect(DB)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS events(
        event_id TEXT PRIMARY KEY,
        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()



def exists(event_id):

    conn=sqlite3.connect(DB)

    r=conn.execute(
        "select event_id from events where event_id=?",
        (event_id,)
    ).fetchone()

    conn.close()

    return r is not None



def save(event_id):

    conn=sqlite3.connect(DB)

    conn.execute(
        "insert or ignore into events(event_id) values(?)",
        (event_id,)
    )

    conn.commit()
    conn.close()
