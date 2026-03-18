"""
Database layer -- Supabase Postgres via REST API.
Falls back to local SQLite if Supabase is not configured.
"""
import json
import logging
import os
import random
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
REST_URL = f"{SUPABASE_URL}/rest/v1" if SUPABASE_URL else ""  # pragma: no cover

_headers = {  # pragma: no cover
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Prefer": "return=representation",
}

_UUID_RE = re.compile(  # pragma: no cover
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Allowed q_type values for PostgREST filter validation
_VALID_TYPES = frozenset(
    {"choice", "truefalse", "multichoice", "scenario_choice", "scenario_multichoice"}
)

# Allowed bank_id pattern
_BANK_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _is_supabase() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _safe_filter_value(value: str) -> str:
    """URL-encode a value for PostgREST filter to prevent injection."""
    return quote(value, safe="")


def _validate_bank_id(value: str) -> str:
    """Validate bank_id format."""
    if not _BANK_ID_RE.match(value):
        raise ValueError("Invalid bank_id format")
    return value


def _supabase_request(method: str, url: str, **kwargs) -> httpx.Response:  # pragma: no cover
    """Execute an HTTP request to Supabase with error handling."""
    try:
        resp = getattr(httpx, method)(url, timeout=10, follow_redirects=True, **kwargs)
        resp.raise_for_status()
        return resp
    except httpx.HTTPStatusError as e:
        logger.error(
            "Supabase %s %s failed: %s %s",
            method.upper(), url, e.response.status_code, e.response.text[:300],
        )
        raise RuntimeError(f"Database request failed ({e.response.status_code})") from e
    except httpx.RequestError as e:
        logger.error("Supabase connection error: %s", e)
        raise RuntimeError("Database connection failed") from e


# ========== Questions ==========

def get_questions(
    chapter: Optional[str] = None,
    difficulty: Optional[int] = None,
    q_type: Optional[str] = None,
    limit: Optional[int] = None,
    exclude_ids: Optional[list[int]] = None,
    bank_id: Optional[str] = None,
) -> list[dict]:
    """Fetch questions with optional filters."""
    if not _is_supabase():
        return _sqlite_get_questions(chapter, difficulty, q_type, limit, exclude_ids, bank_id)

    filters = []
    if bank_id:
        _validate_bank_id(bank_id)
        filters.append(f"bank_id=eq.{_safe_filter_value(bank_id)}")
    if chapter:
        filters.append(f"chapter_group=eq.{_safe_filter_value(chapter)}")
    if difficulty:
        filters.append(f"difficulty=eq.{int(difficulty)}")
    if q_type:
        if q_type not in _VALID_TYPES:
            return []
        filters.append(f"type=eq.{q_type}")
    if exclude_ids:
        id_list = ",".join(str(int(i)) for i in exclude_ids)
        filters.append(f"id=not.in.({id_list})")

    query = "&".join(filters) if filters else ""
    fetch_limit = min((limit or 200) * 3, 600)
    url = f"{REST_URL}/questions?select=*&{query}&limit={fetch_limit}"

    resp = _supabase_request("get", url, headers=_headers)
    rows = resp.json()

    random.shuffle(rows)
    if limit and len(rows) > limit:
        rows = rows[:limit]

    return rows


def get_questions_by_ids(ids: list[int]) -> list[dict]:
    """Fetch specific questions by ID list."""
    if not _is_supabase():
        return _sqlite_get_questions_by_ids(ids)

    if not ids:
        return []

    id_list = ",".join(str(int(i)) for i in ids)
    url = f"{REST_URL}/questions?id=in.({id_list})&select=*"
    resp = _supabase_request("get", url, headers=_headers)
    return resp.json()


def get_chapters(bank_id: Optional[str] = None) -> list[str]:
    """Get distinct chapter groups via RPC."""
    if not _is_supabase():
        return _sqlite_get_chapters(bank_id)

    url = f"{REST_URL}/rpc/get_distinct_chapters"
    payload = {"p_bank_id": None}
    if bank_id:
        _validate_bank_id(bank_id)
        payload["p_bank_id"] = bank_id
    resp = _supabase_request("post", url, headers=_headers, json=payload)
    result = resp.json()
    return result if isinstance(result, list) else []


def get_stats(bank_id: Optional[str] = None) -> dict:
    """Get question bank statistics via RPC."""
    if not _is_supabase():
        return _sqlite_get_stats(bank_id)

    url = f"{REST_URL}/rpc/get_question_stats"
    payload = {"p_bank_id": None}
    if bank_id:
        _validate_bank_id(bank_id)
        payload["p_bank_id"] = bank_id
    resp = _supabase_request("post", url, headers=_headers, json=payload)
    result = resp.json()
    return result if isinstance(result, dict) else {"total": 0, "by_chapter": {}, "by_type": {}}


def delete_question(question_id: int):
    """Delete a question by ID."""
    if not _is_supabase():
        return _sqlite_delete_question(question_id)

    url = f"{REST_URL}/questions?id=eq.{int(question_id)}"
    _supabase_request("delete", url, headers=_headers)


def insert_question(q: dict) -> int:
    """Insert a question and return its ID."""
    if not _is_supabase():
        return _sqlite_insert_question(q)

    payload = {
        "chapter": q["chapter"],
        "chapter_group": q.get("chapter_group"),
        "source_file": q["source_file"],
        "type": q["type"],
        "content": q["content"],
        "option_a": q.get("option_a"),
        "option_b": q.get("option_b"),
        "option_c": q.get("option_c"),
        "option_d": q.get("option_d"),
        "answer": q["answer"],
        "difficulty": q["difficulty"],
        "explanation": q.get("explanation"),
        "scenario_id": q.get("scenario_id"),
        "scenario_text": q.get("scenario_text"),
        "bank_id": q.get("bank_id", "ipas-netzero-mid"),
    }
    url = f"{REST_URL}/questions"
    resp = _supabase_request("post", url, json=payload, headers=_headers)
    return resp.json()[0]["id"]


# ========== Quiz Sessions ==========

def _validate_uuid(value: str, field_name: str) -> str:
    """Validate UUID format to prevent PostgREST filter injection."""
    if not _UUID_RE.match(value):
        raise ValueError(f"Invalid {field_name} format: must be UUID")
    return value


def get_seen_ids(user_id: str, session_id: str) -> set[int]:
    """Get seen question IDs for a user session."""
    if not _is_supabase():
        return set()

    _validate_uuid(session_id, "session_id")
    safe_uid = _safe_filter_value(user_id)

    url = (
        f"{REST_URL}/quiz_sessions"
        f"?user_id=eq.{safe_uid}&id=eq.{session_id}&select=seen_ids"
    )
    resp = _supabase_request("get", url, headers=_headers)
    rows = resp.json()
    if not rows:
        return set()
    return set(rows[0].get("seen_ids") or [])


def mark_seen(user_id: str, session_id: str, question_ids: list[int]):
    """Add question IDs to seen set for a user session."""
    if not _is_supabase():
        return

    _validate_uuid(session_id, "session_id")

    existing = get_seen_ids(user_id, session_id)
    new_seen = sorted(existing | set(question_ids))

    payload = {
        "id": session_id,
        "user_id": user_id,
        "seen_ids": new_seen,
        "updated_at": "now()",
    }
    url = f"{REST_URL}/quiz_sessions"
    _supabase_request(
        "post", url,
        json=payload,
        headers={**_headers, "Prefer": "resolution=merge-duplicates,return=representation"},
    )


def reset_session(user_id: str, session_id: str) -> int:
    """Reset a session. Returns count of cleared IDs."""
    if not _is_supabase():
        return 0

    _validate_uuid(session_id, "session_id")
    safe_uid = _safe_filter_value(user_id)

    existing = get_seen_ids(user_id, session_id)
    url = f"{REST_URL}/quiz_sessions?id=eq.{session_id}&user_id=eq.{safe_uid}"
    _supabase_request("delete", url, headers=_headers)
    return len(existing)


# ========== Quiz History ==========

def save_history_batch(user_id: str, entries: list[dict]) -> int:
    """Bulk insert quiz history entries. Returns count inserted."""
    if not _is_supabase():
        return _sqlite_save_history_batch(user_id, entries)

    if not entries:
        return 0

    url = f"{REST_URL}/quiz_history"
    resp = _supabase_request("post", url, json=entries, headers=_headers)
    return len(resp.json())


def get_history(user_id: str, limit: int = 200, offset: int = 0) -> list[dict]:
    """Paginated fetch of quiz history, newest first."""
    if not _is_supabase():
        return _sqlite_get_history(user_id, limit, offset)

    safe_uid = _safe_filter_value(user_id)
    url = (
        f"{REST_URL}/quiz_history"
        f"?user_id=eq.{safe_uid}&select=*"
        f"&order=answered_at.desc&limit={int(limit)}&offset={int(offset)}"
    )
    resp = _supabase_request("get", url, headers=_headers)
    return resp.json()


def get_weakness_stats(user_id: str) -> list[dict]:
    """Aggregate chapter-level stats for weakness analysis."""
    if not _is_supabase():
        return _sqlite_get_weakness_stats(user_id)

    safe_uid = _safe_filter_value(user_id)
    url = f"{REST_URL}/rpc/get_weakness_stats"
    resp = _supabase_request("post", url, headers=_headers, json={"p_user_id": safe_uid})
    result = resp.json()
    return result if isinstance(result, list) else []


def clear_history(user_id: str) -> int:
    """Delete all history for a user. Returns count deleted."""
    if not _is_supabase():
        return _sqlite_clear_history(user_id)

    safe_uid = _safe_filter_value(user_id)
    # Get count first
    url = f"{REST_URL}/quiz_history?user_id=eq.{safe_uid}&select=id"
    resp = _supabase_request("get", url, headers={**_headers, "Prefer": "count=exact"})
    count = len(resp.json())

    if count > 0:
        url = f"{REST_URL}/quiz_history?user_id=eq.{safe_uid}"
        _supabase_request("delete", url, headers=_headers)

    return count


# ========== Exam Sessions ==========

def create_exam_session(
    user_id: str, bank_id: str, question_ids: list[int],
    shuffle_map: dict, duration_min: int,
) -> dict:
    """Create a new exam session. Returns the created session."""
    if not _is_supabase():
        return _sqlite_create_exam_session(
            user_id, bank_id, question_ids, shuffle_map, duration_min,
        )

    session_id = str(uuid.uuid4())
    payload = {
        "id": session_id,
        "user_id": user_id,
        "bank_id": bank_id,
        "question_ids": question_ids,
        "shuffle_map": shuffle_map,
        "duration_min": duration_min,
        "status": "active",
    }
    url = f"{REST_URL}/exam_sessions"
    resp = _supabase_request("post", url, json=payload, headers=_headers)
    return resp.json()[0]


def get_exam_session(session_id: str, user_id: str) -> Optional[dict]:
    """Fetch an exam session by ID with user_id verification."""
    if not _is_supabase():
        return _sqlite_get_exam_session(session_id, user_id)

    _validate_uuid(session_id, "session_id")
    safe_uid = _safe_filter_value(user_id)

    url = f"{REST_URL}/exam_sessions?id=eq.{session_id}&user_id=eq.{safe_uid}&select=*"
    resp = _supabase_request("get", url, headers=_headers)
    rows = resp.json()
    return rows[0] if rows else None


def submit_exam_session(
    session_id: str, user_id: str,
    score: int, total: int, tab_switches: int,
) -> dict:
    """Mark exam as submitted with final score."""
    if not _is_supabase():
        return _sqlite_submit_exam_session(
            session_id, user_id, score, total, tab_switches,
        )

    _validate_uuid(session_id, "session_id")
    safe_uid = _safe_filter_value(user_id)

    payload = {
        "status": "submitted",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "total": total,
        "tab_switches": tab_switches,
    }
    url = f"{REST_URL}/exam_sessions?id=eq.{session_id}&user_id=eq.{safe_uid}"
    resp = _supabase_request("patch", url, json=payload, headers=_headers)
    rows = resp.json()
    return rows[0] if rows else {}


def increment_tab_switches(session_id: str, user_id: str) -> int:
    """Increment tab_switches and return new count."""
    if not _is_supabase():
        return _sqlite_increment_tab_switches(session_id, user_id)

    session = get_exam_session(session_id, user_id)
    if not session:
        return 0

    new_count = (session.get("tab_switches") or 0) + 1
    _validate_uuid(session_id, "session_id")
    safe_uid = _safe_filter_value(user_id)

    url = f"{REST_URL}/exam_sessions?id=eq.{session_id}&user_id=eq.{safe_uid}"
    _supabase_request("patch", url, json={"tab_switches": new_count}, headers=_headers)
    return new_count


def get_exam_history(user_id: str, limit: int = 20, offset: int = 0) -> list[dict]:
    """List past exam results for a user."""
    if not _is_supabase():
        return _sqlite_get_exam_history(user_id, limit, offset)

    safe_uid = _safe_filter_value(user_id)
    url = (
        f"{REST_URL}/exam_sessions"
        f"?user_id=eq.{safe_uid}&select=id,bank_id,started_at,submitted_at,duration_min,score,total,tab_switches,status"
        f"&order=started_at.desc&limit={int(limit)}&offset={int(offset)}"
    )
    resp = _supabase_request("get", url, headers=_headers)
    return resp.json()


# ========== Init ==========

def init_db():
    if _is_supabase():
        return
    _sqlite_init_db()


def migrate_add_explanation():
    if _is_supabase():
        return
    _sqlite_migrate_add_explanation()


def migrate_add_multichoice_scenario():
    if _is_supabase():
        return
    _sqlite_migrate_add_multichoice_scenario()


def migrate_add_bank_id():
    if _is_supabase():
        return
    _sqlite_migrate_add_bank_id()


def migrate_add_quiz_history():
    if _is_supabase():
        return
    _sqlite_migrate_add_quiz_history()


def migrate_add_exam_sessions():
    if _is_supabase():
        return
    _sqlite_migrate_add_exam_sessions()


# ========== SQLite Fallback (local dev) ==========

_SQLITE_DB = "data/questions.db"


def _sqlite_conn():
    """Create a new SQLite connection with row_factory."""
    conn = sqlite3.connect(_SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_init_db():
    os.makedirs(os.path.dirname(_SQLITE_DB) or ".", exist_ok=True)
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter     TEXT NOT NULL,
            source_file TEXT NOT NULL,
            type        TEXT NOT NULL,
            content     TEXT NOT NULL,
            option_a    TEXT,
            option_b    TEXT,
            option_c    TEXT,
            option_d    TEXT,
            answer      TEXT NOT NULL,
            difficulty  INTEGER NOT NULL CHECK(difficulty IN (1, 2, 3)),
            explanation TEXT,
            scenario_id TEXT,
            scenario_text TEXT,
            chapter_group TEXT,
            bank_id     TEXT NOT NULL DEFAULT 'ipas-netzero-mid',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quiz_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            question_id     INTEGER NOT NULL,
            question_type   TEXT NOT NULL,
            chapter         TEXT,
            content_preview TEXT,
            is_correct      BOOLEAN NOT NULL,
            user_answer     TEXT NOT NULL,
            correct_answer  TEXT,
            answered_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS exam_sessions (
            id            TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            bank_id       TEXT NOT NULL DEFAULT 'ipas-netzero-mid',
            question_ids  TEXT NOT NULL,
            shuffle_map   TEXT,
            started_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            duration_min  INTEGER NOT NULL DEFAULT 60,
            submitted_at  DATETIME,
            score         INTEGER,
            total         INTEGER,
            tab_switches  INTEGER NOT NULL DEFAULT 0,
            status        TEXT NOT NULL DEFAULT 'active'
        )
    """)
    conn.commit()
    conn.close()


def _sqlite_get_questions(
    chapter=None, difficulty=None, q_type=None,
    limit=None, exclude_ids=None, bank_id=None,
) -> list[dict]:
    conn = _sqlite_conn()
    sql = "SELECT * FROM questions WHERE 1=1"
    params: list = []
    if bank_id:
        sql += " AND bank_id = ?"
        params.append(bank_id)
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


def _sqlite_get_questions_by_ids(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    conn = _sqlite_conn()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM questions WHERE id IN ({placeholders})", ids
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _sqlite_get_chapters(bank_id=None) -> list[str]:
    conn = sqlite3.connect(_SQLITE_DB)
    sql = "SELECT DISTINCT chapter_group FROM questions WHERE chapter_group IS NOT NULL"
    params: list = []
    if bank_id:
        sql += " AND bank_id = ?"
        params.append(bank_id)
    sql += " ORDER BY chapter_group"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [r[0] for r in rows]


def _sqlite_get_stats(bank_id=None) -> dict:
    conn = sqlite3.connect(_SQLITE_DB)
    where = " WHERE bank_id = ?" if bank_id else ""
    params = [bank_id] if bank_id else []

    total = conn.execute(f"SELECT COUNT(*) FROM questions{where}", params).fetchone()[0]
    by_chapter = conn.execute(
        f"SELECT chapter_group, COUNT(*) FROM questions{where}"
        + (" AND" if bank_id else " WHERE")
        + " chapter_group IS NOT NULL GROUP BY chapter_group",
        params,
    ).fetchall()
    by_type = conn.execute(
        f"SELECT type, COUNT(*) FROM questions{where} GROUP BY type", params
    ).fetchall()
    conn.close()
    return {"total": total, "by_chapter": dict(by_chapter), "by_type": dict(by_type)}


def _sqlite_delete_question(question_id: int):
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
    conn.commit()
    conn.close()


def _sqlite_insert_question(q: dict) -> int:
    conn = sqlite3.connect(_SQLITE_DB)
    cur = conn.execute("""
        INSERT INTO questions
        (chapter, source_file, type, content, option_a, option_b, option_c, option_d,
         answer, difficulty, explanation, scenario_id, scenario_text, bank_id, chapter_group)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        q["chapter"], q["source_file"], q["type"], q["content"],
        q.get("option_a"), q.get("option_b"), q.get("option_c"), q.get("option_d"),
        q["answer"], q["difficulty"], q.get("explanation"),
        q.get("scenario_id"), q.get("scenario_text"),
        q.get("bank_id", "ipas-netzero-mid"),
        q.get("chapter_group"),
    ))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


# -- Quiz History SQLite --

def _sqlite_save_history_batch(user_id: str, entries: list[dict]) -> int:
    if not entries:
        return 0
    conn = sqlite3.connect(_SQLITE_DB)
    for e in entries:
        conn.execute("""
            INSERT INTO quiz_history
            (user_id, question_id, question_type, chapter, content_preview,
             is_correct, user_answer, correct_answer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, e["question_id"], e["question_type"],
            e.get("chapter"), e.get("content_preview"),
            e["is_correct"], e["user_answer"], e.get("correct_answer"),
        ))
    conn.commit()
    conn.close()
    return len(entries)


def _sqlite_get_history(user_id: str, limit: int, offset: int) -> list[dict]:
    conn = _sqlite_conn()
    rows = conn.execute(
        "SELECT * FROM quiz_history WHERE user_id = ? ORDER BY answered_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _sqlite_get_weakness_stats(user_id: str) -> list[dict]:
    conn = sqlite3.connect(_SQLITE_DB)
    rows = conn.execute("""
        SELECT chapter,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct
        FROM quiz_history
        WHERE user_id = ? AND chapter IS NOT NULL
        GROUP BY chapter
        ORDER BY (CAST(SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS REAL) / COUNT(*)) ASC
    """, (user_id,)).fetchall()
    conn.close()
    return [{"chapter": r[0], "total": r[1], "correct": r[2]} for r in rows]


def _sqlite_clear_history(user_id: str) -> int:
    conn = sqlite3.connect(_SQLITE_DB)
    cur = conn.execute("DELETE FROM quiz_history WHERE user_id = ?", (user_id,))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


# -- Exam Sessions SQLite --

def _sqlite_create_exam_session(
    user_id, bank_id, question_ids, shuffle_map, duration_min,
) -> dict:
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute("""
        INSERT INTO exam_sessions
        (id, user_id, bank_id, question_ids, shuffle_map, started_at, duration_min, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
    """, (
        session_id, user_id, bank_id,
        json.dumps(question_ids), json.dumps(shuffle_map),
        now, duration_min,
    ))
    conn.commit()
    conn.close()
    return {
        "id": session_id, "user_id": user_id, "bank_id": bank_id,
        "question_ids": question_ids, "shuffle_map": shuffle_map,
        "started_at": now, "duration_min": duration_min,
        "status": "active", "tab_switches": 0,
    }


def _sqlite_get_exam_session(session_id, user_id) -> Optional[dict]:
    conn = _sqlite_conn()
    row = conn.execute(
        "SELECT * FROM exam_sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["question_ids"] = json.loads(d["question_ids"]) if isinstance(d["question_ids"], str) else d["question_ids"]
    d["shuffle_map"] = json.loads(d["shuffle_map"]) if isinstance(d["shuffle_map"], str) else d["shuffle_map"]
    return d


def _sqlite_submit_exam_session(session_id, user_id, score, total, tab_switches) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute("""
        UPDATE exam_sessions
        SET status = 'submitted', submitted_at = ?, score = ?, total = ?, tab_switches = ?
        WHERE id = ? AND user_id = ?
    """, (now, score, total, tab_switches, session_id, user_id))
    conn.commit()
    conn.close()
    return {"id": session_id, "status": "submitted", "score": score, "total": total}


def _sqlite_increment_tab_switches(session_id, user_id) -> int:
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute(
        "UPDATE exam_sessions SET tab_switches = tab_switches + 1 WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT tab_switches FROM exam_sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def _sqlite_get_exam_history(user_id, limit, offset) -> list[dict]:
    conn = _sqlite_conn()
    rows = conn.execute(
        "SELECT id, bank_id, started_at, submitted_at, duration_min, score, total, tab_switches, status "
        "FROM exam_sessions WHERE user_id = ? ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# -- Migrations --

def _sqlite_migrate_add_explanation():
    conn = sqlite3.connect(_SQLITE_DB)
    try:
        conn.execute("ALTER TABLE questions ADD COLUMN explanation TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()


def _sqlite_migrate_add_multichoice_scenario():
    conn = sqlite3.connect(_SQLITE_DB)
    for col, col_type in [("scenario_id", "TEXT"), ("scenario_text", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    conn.close()


def _sqlite_migrate_add_bank_id():
    conn = sqlite3.connect(_SQLITE_DB)
    try:
        conn.execute("ALTER TABLE questions ADD COLUMN bank_id TEXT NOT NULL DEFAULT 'ipas-netzero-mid'")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()


def _sqlite_migrate_add_quiz_history():
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quiz_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            question_id     INTEGER NOT NULL,
            question_type   TEXT NOT NULL,
            chapter         TEXT,
            content_preview TEXT,
            is_correct      BOOLEAN NOT NULL,
            user_answer     TEXT NOT NULL,
            correct_answer  TEXT,
            answered_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _sqlite_migrate_add_exam_sessions():
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS exam_sessions (
            id            TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            bank_id       TEXT NOT NULL DEFAULT 'ipas-netzero-mid',
            question_ids  TEXT NOT NULL,
            shuffle_map   TEXT,
            started_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            duration_min  INTEGER NOT NULL DEFAULT 60,
            submitted_at  DATETIME,
            score         INTEGER,
            total         INTEGER,
            tab_switches  INTEGER NOT NULL DEFAULT 0,
            status        TEXT NOT NULL DEFAULT 'active'
        )
    """)
    conn.commit()
    conn.close()
