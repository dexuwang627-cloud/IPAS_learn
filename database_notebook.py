"""
Database layer for wrong answer notebook.
Follows the same dual-backend pattern as database.py.
"""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from database import (
    _is_supabase, _supabase_request, _headers, REST_URL,
    _safe_filter_value, _SQLITE_DB, _sqlite_conn,
    _validate_uuid, get_questions_by_ids,
)

logger = logging.getLogger(__name__)

_VALID_SOURCES = frozenset({"quiz", "exam", "bookmark"})
_VALID_FILTERS = frozenset({"all", "bookmarked", "quiz", "exam"})
_VALID_SORTS = frozenset({"recent", "frequency"})


# ========== Public API ==========

def migrate_add_wrong_notebook():
    """Create wrong_notebook table if it doesn't exist."""
    if _is_supabase():
        return
    _sqlite_migrate_add_wrong_notebook()


def upsert_wrong_answers(
    user_id: str, question_ids: list[int], source: str,
) -> int:
    """Bulk upsert wrong answers. Returns count of affected rows."""
    if not question_ids:
        return 0
    if source not in _VALID_SOURCES:
        raise ValueError(f"Invalid source: {source}")
    if not _is_supabase():
        return _sqlite_upsert_wrong_answers(user_id, question_ids, source)
    return _supabase_upsert_wrong_answers(user_id, question_ids, source)


def toggle_bookmark(user_id: str, question_id: int) -> dict:
    """Toggle bookmark on a question. Creates entry if not exists.
    Returns {"bookmarked": bool}.
    """
    if not _is_supabase():
        return _sqlite_toggle_bookmark(user_id, question_id)
    return _supabase_toggle_bookmark(user_id, question_id)


def get_notebook_entries(
    user_id: str,
    filter_type: str = "all",
    chapter: Optional[str] = None,
    sort: str = "recent",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Get notebook entries with question data. Returns (items, total)."""
    if filter_type not in _VALID_FILTERS:
        raise ValueError(f"Invalid filter: {filter_type}")
    if sort not in _VALID_SORTS:
        raise ValueError(f"Invalid sort: {sort}")
    if not _is_supabase():
        return _sqlite_get_notebook_entries(
            user_id, filter_type, chapter, sort, limit, offset,
        )
    return _supabase_get_notebook_entries(
        user_id, filter_type, chapter, sort, limit, offset,
    )


def get_notebook_stats(user_id: str) -> dict:
    """Get notebook summary stats."""
    if not _is_supabase():
        return _sqlite_get_notebook_stats(user_id)
    return _supabase_get_notebook_stats(user_id)


def get_notebook_question_ids(
    user_id: str,
    filter_type: str = "all",
    chapter: Optional[str] = None,
    limit: int = 50,
) -> list[int]:
    """Get question IDs from notebook for practice."""
    if not _is_supabase():
        return _sqlite_get_notebook_question_ids(
            user_id, filter_type, chapter, limit,
        )
    return _supabase_get_notebook_question_ids(
        user_id, filter_type, chapter, limit,
    )


def remove_notebook_entry(user_id: str, question_id: int) -> bool:
    """Remove entry from notebook. Returns True if deleted."""
    if not _is_supabase():
        return _sqlite_remove_notebook_entry(user_id, question_id)
    return _supabase_remove_notebook_entry(user_id, question_id)


# ========== SQLite Implementation ==========

def _sqlite_migrate_add_wrong_notebook():
    conn = sqlite3.connect(_SQLITE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wrong_notebook (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL,
            question_id     INTEGER NOT NULL,
            source          TEXT NOT NULL CHECK(source IN ('quiz', 'exam', 'bookmark')),
            wrong_count     INTEGER NOT NULL DEFAULT 1,
            first_wrong_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_wrong_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            bookmarked      BOOLEAN NOT NULL DEFAULT 0,
            UNIQUE(user_id, question_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_wrong_notebook_user
        ON wrong_notebook(user_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_wrong_notebook_user_bookmarked
        ON wrong_notebook(user_id, bookmarked)
    """)
    conn.commit()
    conn.close()


def _sqlite_upsert_wrong_answers(
    user_id: str, question_ids: list[int], source: str,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(_SQLITE_DB)
    count = 0
    for qid in question_ids:
        cur = conn.execute(
            "SELECT id, wrong_count FROM wrong_notebook "
            "WHERE user_id = ? AND question_id = ?",
            (user_id, qid),
        )
        existing = cur.fetchone()
        if existing:
            conn.execute(
                "UPDATE wrong_notebook SET wrong_count = wrong_count + 1, "
                "last_wrong_at = ? WHERE id = ?",
                (now, existing[0]),
            )
        else:
            conn.execute(
                "INSERT INTO wrong_notebook "
                "(user_id, question_id, source, wrong_count, first_wrong_at, last_wrong_at) "
                "VALUES (?, ?, ?, 1, ?, ?)",
                (user_id, qid, source, now, now),
            )
        count += 1
    conn.commit()
    conn.close()
    return count


def _sqlite_toggle_bookmark(user_id: str, question_id: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(_SQLITE_DB)
    cur = conn.execute(
        "SELECT id, bookmarked FROM wrong_notebook "
        "WHERE user_id = ? AND question_id = ?",
        (user_id, question_id),
    )
    existing = cur.fetchone()
    if existing:
        new_val = not bool(existing[1])
        conn.execute(
            "UPDATE wrong_notebook SET bookmarked = ? WHERE id = ?",
            (new_val, existing[0]),
        )
    else:
        new_val = True
        conn.execute(
            "INSERT INTO wrong_notebook "
            "(user_id, question_id, source, wrong_count, first_wrong_at, "
            "last_wrong_at, bookmarked) VALUES (?, ?, 'bookmark', 0, ?, ?, 1)",
            (user_id, question_id, now, now),
        )
    conn.commit()
    conn.close()
    return {"bookmarked": new_val}


def _sqlite_get_notebook_entries(
    user_id: str, filter_type: str, chapter: Optional[str],
    sort: str, limit: int, offset: int,
) -> tuple[list[dict], int]:
    conn = sqlite3.connect(_SQLITE_DB)
    conn.row_factory = sqlite3.Row

    where = "n.user_id = ?"
    params: list = [user_id]

    if filter_type == "bookmarked":
        where += " AND n.bookmarked = 1"
    elif filter_type in ("quiz", "exam"):
        where += " AND n.source = ?"
        params.append(filter_type)

    if chapter:
        where += " AND q.chapter_group = ?"
        params.append(chapter)

    order = "n.last_wrong_at DESC" if sort == "recent" else "n.wrong_count DESC"

    count_sql = (
        f"SELECT COUNT(*) FROM wrong_notebook n "
        f"LEFT JOIN questions q ON n.question_id = q.id "
        f"WHERE {where}"
    )
    total = conn.execute(count_sql, params).fetchone()[0]

    query_sql = (
        f"SELECT n.*, q.content, q.type, q.chapter_group, q.difficulty, "
        f"q.option_a, q.option_b, q.option_c, q.option_d, "
        f"q.answer, q.explanation, q.bank_id "
        f"FROM wrong_notebook n "
        f"LEFT JOIN questions q ON n.question_id = q.id "
        f"WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?"
    )
    rows = conn.execute(query_sql, params + [limit, offset]).fetchall()
    conn.close()

    items = []
    for r in rows:
        d = dict(r)
        items.append({
            "question_id": d["question_id"],
            "source": d["source"],
            "wrong_count": d["wrong_count"],
            "first_wrong_at": d["first_wrong_at"],
            "last_wrong_at": d["last_wrong_at"],
            "bookmarked": bool(d["bookmarked"]),
            "question": {
                "id": d["question_id"],
                "content": d["content"],
                "type": d["type"],
                "chapter_group": d["chapter_group"],
                "difficulty": d["difficulty"],
                "option_a": d["option_a"],
                "option_b": d["option_b"],
                "option_c": d["option_c"],
                "option_d": d["option_d"],
                "answer": d["answer"],
                "explanation": d["explanation"],
                "bank_id": d.get("bank_id"),
            },
        })
    return items, total


def _sqlite_get_notebook_stats(user_id: str) -> dict:
    conn = sqlite3.connect(_SQLITE_DB)
    total = conn.execute(
        "SELECT COUNT(*) FROM wrong_notebook WHERE user_id = ?",
        (user_id,),
    ).fetchone()[0]
    bookmarked = conn.execute(
        "SELECT COUNT(*) FROM wrong_notebook WHERE user_id = ? AND bookmarked = 1",
        (user_id,),
    ).fetchone()[0]
    by_source = conn.execute(
        "SELECT source, COUNT(*) FROM wrong_notebook "
        "WHERE user_id = ? GROUP BY source",
        (user_id,),
    ).fetchall()
    top_chapters = conn.execute(
        "SELECT q.chapter_group, COUNT(*) as cnt FROM wrong_notebook n "
        "LEFT JOIN questions q ON n.question_id = q.id "
        "WHERE n.user_id = ? AND q.chapter_group IS NOT NULL "
        "GROUP BY q.chapter_group ORDER BY cnt DESC LIMIT 5",
        (user_id,),
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "bookmarked": bookmarked,
        "by_source": dict(by_source),
        "top_chapters": [{"chapter": c[0], "count": c[1]} for c in top_chapters],
    }


def _sqlite_get_notebook_question_ids(
    user_id: str, filter_type: str, chapter: Optional[str], limit: int,
) -> list[int]:
    conn = sqlite3.connect(_SQLITE_DB)
    where = "n.user_id = ?"
    params: list = [user_id]

    if filter_type == "bookmarked":
        where += " AND n.bookmarked = 1"
    elif filter_type in ("quiz", "exam"):
        where += " AND n.source = ?"
        params.append(filter_type)

    if chapter:
        where += " AND q.chapter_group = ?"
        params.append(chapter)

    rows = conn.execute(
        f"SELECT n.question_id FROM wrong_notebook n "
        f"LEFT JOIN questions q ON n.question_id = q.id "
        f"WHERE {where} ORDER BY RANDOM() LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def _sqlite_remove_notebook_entry(user_id: str, question_id: int) -> bool:
    conn = sqlite3.connect(_SQLITE_DB)
    cur = conn.execute(
        "DELETE FROM wrong_notebook WHERE user_id = ? AND question_id = ?",
        (user_id, question_id),
    )
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


# ========== Supabase Implementation ==========

def _supabase_upsert_wrong_answers(
    user_id: str, question_ids: list[int], source: str,
) -> int:  # pragma: no cover
    safe_uid = _safe_filter_value(user_id)
    now = datetime.now(timezone.utc).isoformat()

    # Get existing entries
    id_list = ",".join(str(int(qid)) for qid in question_ids)
    url = (
        f"{REST_URL}/wrong_notebook"
        f"?user_id=eq.{safe_uid}&question_id=in.({id_list})"
        f"&select=id,question_id,wrong_count"
    )
    resp = _supabase_request("get", url, headers=_headers)
    existing = {r["question_id"]: r for r in resp.json()}

    # Update existing entries (increment wrong_count)
    for qid, row in existing.items():
        patch_url = f"{REST_URL}/wrong_notebook?id=eq.{row['id']}"
        _supabase_request("patch", patch_url, json={
            "wrong_count": row["wrong_count"] + 1,
            "last_wrong_at": now,
        }, headers=_headers)

    # Insert new entries
    new_ids = [qid for qid in question_ids if qid not in existing]
    if new_ids:
        rows = [
            {
                "user_id": user_id,
                "question_id": qid,
                "source": source,
                "wrong_count": 1,
                "first_wrong_at": now,
                "last_wrong_at": now,
                "bookmarked": False,
            }
            for qid in new_ids
        ]
        _supabase_request("post", f"{REST_URL}/wrong_notebook",
                          json=rows, headers=_headers)

    return len(question_ids)


def _supabase_toggle_bookmark(user_id: str, question_id: int) -> dict:  # pragma: no cover
    safe_uid = _safe_filter_value(user_id)
    now = datetime.now(timezone.utc).isoformat()

    url = (
        f"{REST_URL}/wrong_notebook"
        f"?user_id=eq.{safe_uid}&question_id=eq.{question_id}"
        f"&select=id,bookmarked"
    )
    resp = _supabase_request("get", url, headers=_headers)
    rows = resp.json()

    if rows:
        new_val = not rows[0]["bookmarked"]
        patch_url = f"{REST_URL}/wrong_notebook?id=eq.{rows[0]['id']}"
        _supabase_request("patch", patch_url, json={"bookmarked": new_val},
                          headers=_headers)
        return {"bookmarked": new_val}

    _supabase_request("post", f"{REST_URL}/wrong_notebook", json={
        "user_id": user_id,
        "question_id": question_id,
        "source": "bookmark",
        "wrong_count": 0,
        "first_wrong_at": now,
        "last_wrong_at": now,
        "bookmarked": True,
    }, headers=_headers)
    return {"bookmarked": True}


def _supabase_get_notebook_entries(
    user_id: str, filter_type: str, chapter: Optional[str],
    sort: str, limit: int, offset: int,
) -> tuple[list[dict], int]:  # pragma: no cover
    safe_uid = _safe_filter_value(user_id)
    url = (
        f"{REST_URL}/wrong_notebook"
        f"?user_id=eq.{safe_uid}"
        f"&select=*,questions(*)"
    )
    if filter_type == "bookmarked":
        url += "&bookmarked=eq.true"
    elif filter_type in ("quiz", "exam"):
        url += f"&source=eq.{filter_type}"

    order = "last_wrong_at.desc" if sort == "recent" else "wrong_count.desc"
    url += f"&order={order}&limit={limit}&offset={offset}"

    count_headers = {**_headers, "Prefer": "count=exact"}
    resp = _supabase_request("get", url, headers=count_headers)
    total = int(resp.headers.get("content-range", "0/0").split("/")[-1] or 0)

    items = []
    for r in resp.json():
        q = r.get("questions") or {}
        items.append({
            "question_id": r["question_id"],
            "source": r["source"],
            "wrong_count": r["wrong_count"],
            "first_wrong_at": r["first_wrong_at"],
            "last_wrong_at": r["last_wrong_at"],
            "bookmarked": r["bookmarked"],
            "question": q,
        })
    return items, total


def _supabase_get_notebook_stats(user_id: str) -> dict:  # pragma: no cover
    safe_uid = _safe_filter_value(user_id)
    url = f"{REST_URL}/wrong_notebook?user_id=eq.{safe_uid}&select=source,bookmarked"
    resp = _supabase_request("get", url, headers=_headers)
    rows = resp.json()

    total = len(rows)
    bookmarked = sum(1 for r in rows if r["bookmarked"])
    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1

    return {
        "total": total,
        "bookmarked": bookmarked,
        "by_source": by_source,
        "top_chapters": [],
    }


def _supabase_get_notebook_question_ids(
    user_id: str, filter_type: str, chapter: Optional[str], limit: int,
) -> list[int]:  # pragma: no cover
    safe_uid = _safe_filter_value(user_id)
    url = (
        f"{REST_URL}/wrong_notebook"
        f"?user_id=eq.{safe_uid}&select=question_id"
    )
    if filter_type == "bookmarked":
        url += "&bookmarked=eq.true"
    elif filter_type in ("quiz", "exam"):
        url += f"&source=eq.{filter_type}"
    url += f"&limit={limit}"
    resp = _supabase_request("get", url, headers=_headers)
    return [r["question_id"] for r in resp.json()]


def _supabase_remove_notebook_entry(
    user_id: str, question_id: int,
) -> bool:  # pragma: no cover
    safe_uid = _safe_filter_value(user_id)
    url = (
        f"{REST_URL}/wrong_notebook"
        f"?user_id=eq.{safe_uid}&question_id=eq.{question_id}"
    )
    resp = _supabase_request("delete", url, headers=_headers)
    return len(resp.json()) > 0
