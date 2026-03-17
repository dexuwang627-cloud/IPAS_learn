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
            explanation TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def insert_question(q: dict, db_path: str = DEFAULT_DB) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.execute("""
        INSERT INTO questions
        (chapter, source_file, type, content, option_a, option_b, option_c, option_d,
         answer, difficulty, explanation, scenario_id, scenario_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        q["chapter"], q["source_file"], q["type"], q["content"],
        q.get("option_a"), q.get("option_b"), q.get("option_c"), q.get("option_d"),
        q["answer"], q["difficulty"], q.get("explanation"),
        q.get("scenario_id"), q.get("scenario_text"),
    ))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id

def get_questions(
    chapter: Optional[str] = None,
    difficulty: Optional[int] = None,
    q_type: Optional[str] = None,
    limit: Optional[int] = None,
    exclude_ids: Optional[list[int]] = None,
    db_path: str = DEFAULT_DB
) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM questions WHERE 1=1"
    params = []
    if chapter:
        sql += " AND chapter_group = ?"
        params.append(chapter)
    if difficulty:
        sql += " AND difficulty = ?"
        params.append(difficulty)
    if q_type:
        sql += " AND type = ?"
        params.append(q_type)
    if exclude_ids:
        placeholders = ",".join("?" for _ in exclude_ids)
        sql += f" AND id NOT IN ({placeholders})"
        params.extend(exclude_ids)
    sql += " ORDER BY RANDOM()"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_chapters(db_path: str = DEFAULT_DB) -> list[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT DISTINCT chapter_group FROM questions WHERE chapter_group IS NOT NULL ORDER BY chapter_group"
    ).fetchall()
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
        "SELECT chapter_group, COUNT(*) FROM questions WHERE chapter_group IS NOT NULL GROUP BY chapter_group"
    ).fetchall()
    by_type = conn.execute(
        "SELECT type, COUNT(*) FROM questions GROUP BY type"
    ).fetchall()
    conn.close()
    return {"total": total, "by_chapter": dict(by_chapter), "by_type": dict(by_type)}

def migrate_add_explanation(db_path: str = DEFAULT_DB):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("ALTER TABLE questions ADD COLUMN explanation TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.close()


def migrate_add_multichoice_scenario(db_path: str = DEFAULT_DB):
    """新增複選題 + 情境題支援"""
    conn = sqlite3.connect(db_path)

    # 放寬 type CHECK constraint — SQLite 不支援 ALTER CHECK，
    # 但我們的 CHECK 寫在 CREATE TABLE 裡，已存在的表不會被重建。
    # 所以改用 insert 時不帶 CHECK，靠應用層驗證。
    # 新增 scenario 欄位
    for col, col_type in [
        ("scenario_id", "TEXT"),
        ("scenario_text", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

    # 移除舊的 type CHECK — 重建表
    # 檢查是否已經支援新 type
    try:
        conn.execute(
            "INSERT INTO questions (chapter, source_file, type, content, answer, difficulty) "
            "VALUES ('_test', '_test', 'multichoice', '_test', 'AB', 1)"
        )
        conn.execute("DELETE FROM questions WHERE chapter='_test'")
        conn.commit()
    except sqlite3.IntegrityError:
        # CHECK constraint 擋住了，需要重建表
        conn.execute("PRAGMA foreign_keys=off")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS questions_new (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter        TEXT NOT NULL,
                source_file    TEXT NOT NULL,
                type           TEXT NOT NULL CHECK(type IN ('choice', 'truefalse', 'multichoice', 'scenario_choice', 'scenario_multichoice')),
                content        TEXT NOT NULL,
                option_a       TEXT,
                option_b       TEXT,
                option_c       TEXT,
                option_d       TEXT,
                answer         TEXT NOT NULL,
                difficulty     INTEGER NOT NULL CHECK(difficulty IN (1, 2, 3)),
                explanation    TEXT,
                scenario_id    TEXT,
                scenario_text  TEXT,
                created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            INSERT INTO questions_new
                (id, chapter, source_file, type, content, option_a, option_b,
                 option_c, option_d, answer, difficulty, explanation, created_at)
            SELECT id, chapter, source_file, type, content, option_a, option_b,
                   option_c, option_d, answer, difficulty, explanation, created_at
            FROM questions
        """)
        conn.execute("DROP TABLE questions")
        conn.execute("ALTER TABLE questions_new RENAME TO questions")
        conn.execute("PRAGMA foreign_keys=on")
        conn.commit()

    conn.close()
