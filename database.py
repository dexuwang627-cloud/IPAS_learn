import sqlite3
import os
from typing import Optional

DEFAULT_DB = "data/questions.db"

def init_db(db_path: str = DEFAULT_DB):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter     TEXT NOT NULL,
            source_file TEXT NOT NULL,
            type        TEXT NOT NULL CHECK(type IN ('choice', 'truefalse')),
            content     TEXT NOT NULL,
            option_a    TEXT,
            option_b    TEXT,
            option_c    TEXT,
            option_d    TEXT,
            answer      TEXT NOT NULL,
            difficulty  INTEGER NOT NULL CHECK(difficulty IN (1, 2, 3)),
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def insert_question(q: dict, db_path: str = DEFAULT_DB):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO questions
        (chapter, source_file, type, content, option_a, option_b, option_c, option_d, answer, difficulty)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        q["chapter"], q["source_file"], q["type"], q["content"],
        q.get("option_a"), q.get("option_b"), q.get("option_c"), q.get("option_d"),
        q["answer"], q["difficulty"]
    ))
    conn.commit()
    conn.close()

def get_questions(
    chapter: Optional[str] = None,
    difficulty: Optional[int] = None,
    q_type: Optional[str] = None,
    limit: Optional[int] = None,
    db_path: str = DEFAULT_DB
) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM questions WHERE 1=1"
    params = []
    if chapter:
        sql += " AND chapter = ?"
        params.append(chapter)
    if difficulty:
        sql += " AND difficulty = ?"
        params.append(difficulty)
    if q_type:
        sql += " AND type = ?"
        params.append(q_type)
    sql += " ORDER BY RANDOM()"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_chapters(db_path: str = DEFAULT_DB) -> list[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT DISTINCT chapter FROM questions ORDER BY chapter").fetchall()
    conn.close()
    return [r[0] for r in rows]

def delete_question(question_id: int, db_path: str = DEFAULT_DB):
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
    conn.commit()
    conn.close()

def get_stats(db_path: str = DEFAULT_DB) -> dict:
    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    by_chapter = conn.execute(
        "SELECT chapter, COUNT(*) FROM questions GROUP BY chapter"
    ).fetchall()
    conn.close()
    return {"total": total, "by_chapter": dict(by_chapter)}
