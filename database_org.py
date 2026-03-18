"""
Database layer for organizations, members, and daily usage tracking.
Follows the same dual-backend pattern as database.py.
"""
import logging
import secrets
import sqlite3
import string
from datetime import date, datetime, timezone
from typing import Optional

from database import (
    _is_supabase, _supabase_request, _headers, REST_URL,
    _safe_filter_value, _SQLITE_DB, _sqlite_conn,
)

logger = logging.getLogger(__name__)

_INVITE_CODE_LENGTH = 8
_INVITE_CODE_CHARS = string.ascii_uppercase + string.digits


def _generate_invite_code() -> str:
    """Generate a cryptographically random invite code."""
    return "".join(secrets.choice(_INVITE_CODE_CHARS) for _ in range(_INVITE_CODE_LENGTH))


# ========== Migration ==========

def migrate_add_org_tables():
    """Create organizations, org_members, daily_usage tables if they don't exist."""
    if _is_supabase():
        return
    _sqlite_migrate_add_org_tables()


def _sqlite_migrate_add_org_tables():
    conn = _sqlite_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                invite_code TEXT NOT NULL UNIQUE,
                seat_limit INTEGER NOT NULL DEFAULT 10,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS org_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id INTEGER NOT NULL,
                user_id TEXT NOT NULL UNIQUE,
                joined_at TEXT NOT NULL,
                FOREIGN KEY (org_id) REFERENCES organizations(id)
            );

            CREATE TABLE IF NOT EXISTS daily_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                question_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, usage_date)
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ========== Organizations ==========

def create_org(name: str, seat_limit: int, created_by: str) -> dict:
    """Create a new organization with a unique invite code."""
    if not _is_supabase():
        return _sqlite_create_org(name, seat_limit, created_by)
    return _supabase_create_org(name, seat_limit, created_by)


def get_org(org_id: int) -> Optional[dict]:
    """Get organization by ID."""
    if not _is_supabase():
        return _sqlite_get_org(org_id)
    return _supabase_get_org(org_id)


def get_org_by_invite_code(invite_code: str) -> Optional[dict]:
    """Find organization by invite code."""
    if not _is_supabase():
        return _sqlite_get_org_by_invite_code(invite_code)
    return _supabase_get_org_by_invite_code(invite_code)


def update_org(org_id: int, **kwargs) -> Optional[dict]:
    """Update organization fields. Accepts: name, seat_limit, is_active."""
    allowed = {"name", "seat_limit", "is_active"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_org(org_id)
    if not _is_supabase():
        return _sqlite_update_org(org_id, updates)
    return _supabase_update_org(org_id, updates)


def list_orgs() -> list[dict]:
    """List all organizations."""
    if not _is_supabase():
        return _sqlite_list_orgs()
    return _supabase_list_orgs()


# ========== Members ==========

def add_member(org_id: int, user_id: str) -> dict:
    """Add a user to an organization. Raises ValueError if seats full or org inactive."""
    if not _is_supabase():
        return _sqlite_add_member(org_id, user_id)
    return _supabase_add_member(org_id, user_id)


def remove_member(org_id: int, user_id: str) -> bool:
    """Remove a user from an organization. Returns True if removed."""
    if not _is_supabase():
        return _sqlite_remove_member(org_id, user_id)
    return _supabase_remove_member(org_id, user_id)


def list_members(org_id: int) -> list[dict]:
    """List all members of an organization."""
    if not _is_supabase():
        return _sqlite_list_members(org_id)
    return _supabase_list_members(org_id)


def count_seats(org_id: int) -> int:
    """Count current members in an organization."""
    if not _is_supabase():
        return _sqlite_count_seats(org_id)
    return _supabase_count_seats(org_id)


def get_user_org(user_id: str) -> Optional[dict]:
    """Get the organization a user belongs to. Returns {org_id, org_name, ...} or None."""
    if not _is_supabase():
        return _sqlite_get_user_org(user_id)
    return _supabase_get_user_org(user_id)


# ========== Daily Usage ==========

def increment_daily_usage(user_id: str, count: int = 1) -> None:
    """Increment today's question usage for a user."""
    if not _is_supabase():
        _sqlite_increment_daily_usage(user_id, count)
        return
    _supabase_increment_daily_usage(user_id, count)


def get_daily_usage(user_id: str) -> int:
    """Get today's question count for a user."""
    if not _is_supabase():
        return _sqlite_get_daily_usage(user_id)
    return _supabase_get_daily_usage(user_id)


def check_daily_limit(user_id: str, limit: int = 5) -> bool:
    """Check if user is still under the daily question limit. Returns True if allowed."""
    return get_daily_usage(user_id) < limit


# ========== SQLite Implementations ==========

def _sqlite_create_org(name: str, seat_limit: int, created_by: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conn = _sqlite_conn()
    try:
        # Retry up to 3 times for invite code collision
        for _ in range(3):
            invite_code = _generate_invite_code()
            try:
                cur = conn.execute(
                    """INSERT INTO organizations (name, invite_code, seat_limit, created_by, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (name, invite_code, seat_limit, created_by, now, now),
                )
                conn.commit()
                return {
                    "id": cur.lastrowid,
                    "name": name,
                    "invite_code": invite_code,
                    "seat_limit": seat_limit,
                    "is_active": True,
                    "created_by": created_by,
                    "created_at": now,
                    "updated_at": now,
                }
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("Failed to generate unique invite code")
    finally:
        conn.close()


def _sqlite_get_org(org_id: int) -> Optional[dict]:
    conn = _sqlite_conn()
    try:
        row = conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
        return _row_to_org(row) if row else None
    finally:
        conn.close()


def _sqlite_get_org_by_invite_code(invite_code: str) -> Optional[dict]:
    conn = _sqlite_conn()
    try:
        row = conn.execute(
            "SELECT * FROM organizations WHERE invite_code = ? AND is_active = 1",
            (invite_code,),
        ).fetchone()
        return _row_to_org(row) if row else None
    finally:
        conn.close()


def _sqlite_update_org(org_id: int, updates: dict) -> Optional[dict]:
    now = datetime.now(timezone.utc).isoformat()
    conn = _sqlite_conn()
    try:
        # Convert is_active bool to int for SQLite
        sql_updates = dict(updates)
        if "is_active" in sql_updates:
            sql_updates["is_active"] = 1 if sql_updates["is_active"] else 0
        sql_updates["updated_at"] = now

        set_clause = ", ".join(f"{k} = ?" for k in sql_updates)
        values = list(sql_updates.values()) + [org_id]
        cur = conn.execute(
            f"UPDATE organizations SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        return _sqlite_get_org(org_id)
    finally:
        conn.close()


def _sqlite_list_orgs() -> list[dict]:
    conn = _sqlite_conn()
    try:
        rows = conn.execute("SELECT * FROM organizations ORDER BY created_at DESC").fetchall()
        return [_row_to_org(r) for r in rows]
    finally:
        conn.close()


def _sqlite_add_member(org_id: int, user_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conn = _sqlite_conn()
    try:
        # Single transaction: check org active, seat count, duplicate, then insert
        org = conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
        if not org or not org["is_active"]:
            raise ValueError("Organization is not active")

        current = conn.execute(
            "SELECT COUNT(*) as cnt FROM org_members WHERE org_id = ?", (org_id,)
        ).fetchone()["cnt"]
        if current >= org["seat_limit"]:
            raise ValueError(f"Seat limit reached ({org['seat_limit']})")

        try:
            conn.execute(
                "INSERT INTO org_members (org_id, user_id, joined_at) VALUES (?, ?, ?)",
                (org_id, user_id, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("User already belongs to an organization")

        return {"org_id": org_id, "user_id": user_id, "joined_at": now}
    finally:
        conn.close()


def _sqlite_remove_member(org_id: int, user_id: str) -> bool:
    conn = _sqlite_conn()
    try:
        cur = conn.execute(
            "DELETE FROM org_members WHERE org_id = ? AND user_id = ?",
            (org_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _sqlite_list_members(org_id: int) -> list[dict]:
    conn = _sqlite_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM org_members WHERE org_id = ? ORDER BY joined_at",
            (org_id,),
        ).fetchall()
        return [{"id": r["id"], "org_id": r["org_id"], "user_id": r["user_id"], "joined_at": r["joined_at"]} for r in rows]
    finally:
        conn.close()


def _sqlite_count_seats(org_id: int) -> int:
    conn = _sqlite_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM org_members WHERE org_id = ?", (org_id,)
        ).fetchone()
        return row["cnt"]
    finally:
        conn.close()


def _sqlite_get_user_org(user_id: str) -> Optional[dict]:
    conn = _sqlite_conn()
    try:
        row = conn.execute(
            """SELECT m.org_id, o.name as org_name, o.invite_code, o.seat_limit, o.is_active, m.joined_at
               FROM org_members m
               JOIN organizations o ON o.id = m.org_id
               WHERE m.user_id = ?""",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "org_id": row["org_id"],
            "org_name": row["org_name"],
            "invite_code": row["invite_code"],
            "seat_limit": row["seat_limit"],
            "is_active": bool(row["is_active"]),
            "joined_at": row["joined_at"],
        }
    finally:
        conn.close()


def _sqlite_increment_daily_usage(user_id: str, count: int) -> None:
    today = date.today().isoformat()
    conn = _sqlite_conn()
    try:
        # Upsert: try INSERT, on conflict UPDATE
        conn.execute(
            """INSERT INTO daily_usage (user_id, usage_date, question_count)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, usage_date)
               DO UPDATE SET question_count = question_count + excluded.question_count""",
            (user_id, today, count),
        )
        conn.commit()
    finally:
        conn.close()


def _sqlite_get_daily_usage(user_id: str) -> int:
    today = date.today().isoformat()
    conn = _sqlite_conn()
    try:
        row = conn.execute(
            "SELECT question_count FROM daily_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        ).fetchone()
        return row["question_count"] if row else 0
    finally:
        conn.close()


# ========== Supabase Implementations ==========

def _supabase_create_org(name: str, seat_limit: int, created_by: str) -> dict:  # pragma: no cover
    now = datetime.now(timezone.utc).isoformat()
    invite_code = _generate_invite_code()
    payload = {
        "name": name,
        "invite_code": invite_code,
        "seat_limit": seat_limit,
        "is_active": True,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    resp = _supabase_request("post", f"{REST_URL}/organizations", headers=_headers, json=payload)
    return resp.json()[0]


def _supabase_get_org(org_id: int) -> Optional[dict]:  # pragma: no cover
    resp = _supabase_request(
        "get", f"{REST_URL}/organizations?id=eq.{org_id}", headers=_headers,
    )
    rows = resp.json()
    return rows[0] if rows else None


def _supabase_get_org_by_invite_code(invite_code: str) -> Optional[dict]:  # pragma: no cover
    safe = _safe_filter_value(invite_code)
    resp = _supabase_request(
        "get",
        f"{REST_URL}/organizations?invite_code=eq.{safe}&is_active=eq.true",
        headers=_headers,
    )
    rows = resp.json()
    return rows[0] if rows else None


def _supabase_update_org(org_id: int, updates: dict) -> Optional[dict]:  # pragma: no cover
    now = datetime.now(timezone.utc).isoformat()
    payload = {**updates, "updated_at": now}
    resp = _supabase_request(
        "patch", f"{REST_URL}/organizations?id=eq.{org_id}", headers=_headers, json=payload,
    )
    rows = resp.json()
    return rows[0] if rows else None


def _supabase_list_orgs() -> list[dict]:  # pragma: no cover
    resp = _supabase_request(
        "get", f"{REST_URL}/organizations?order=created_at.desc", headers=_headers,
    )
    return resp.json()


def _supabase_add_member(org_id: int, user_id: str) -> dict:  # pragma: no cover
    org = _supabase_get_org(org_id)
    if not org or not org.get("is_active"):
        raise ValueError("Organization is not active")

    count = _supabase_count_seats(org_id)
    if count >= org["seat_limit"]:
        raise ValueError(f"Seat limit reached ({org['seat_limit']})")

    now = datetime.now(timezone.utc).isoformat()
    payload = {"org_id": org_id, "user_id": user_id, "joined_at": now}
    resp = _supabase_request("post", f"{REST_URL}/org_members", headers=_headers, json=payload)
    return resp.json()[0]


def _supabase_remove_member(org_id: int, user_id: str) -> bool:  # pragma: no cover
    safe_uid = _safe_filter_value(user_id)
    resp = _supabase_request(
        "delete",
        f"{REST_URL}/org_members?org_id=eq.{org_id}&user_id=eq.{safe_uid}",
        headers=_headers,
    )
    return len(resp.json()) > 0


def _supabase_list_members(org_id: int) -> list[dict]:  # pragma: no cover
    resp = _supabase_request(
        "get",
        f"{REST_URL}/org_members?org_id=eq.{org_id}&order=joined_at",
        headers=_headers,
    )
    return resp.json()


def _supabase_count_seats(org_id: int) -> int:  # pragma: no cover
    resp = _supabase_request(
        "get",
        f"{REST_URL}/org_members?org_id=eq.{org_id}&select=id",
        headers={**_headers, "Prefer": "count=exact"},
    )
    count_header = resp.headers.get("content-range", "")
    # Format: "0-N/total" or "*/0"
    if "/" in count_header:
        return int(count_header.split("/")[1])
    return len(resp.json())


def _supabase_get_user_org(user_id: str) -> Optional[dict]:  # pragma: no cover
    safe_uid = _safe_filter_value(user_id)
    resp = _supabase_request(
        "get",
        f"{REST_URL}/org_members?user_id=eq.{safe_uid}&select=org_id,joined_at,organizations(name,invite_code,seat_limit,is_active)",
        headers=_headers,
    )
    rows = resp.json()
    if not rows:
        return None
    r = rows[0]
    org = r.get("organizations", {})
    return {
        "org_id": r["org_id"],
        "org_name": org.get("name"),
        "invite_code": org.get("invite_code"),
        "seat_limit": org.get("seat_limit"),
        "is_active": org.get("is_active"),
        "joined_at": r["joined_at"],
    }


def _supabase_increment_daily_usage(user_id: str, count: int) -> None:  # pragma: no cover
    today = date.today().isoformat()
    safe_uid = _safe_filter_value(user_id)
    # Check if row exists
    resp = _supabase_request(
        "get",
        f"{REST_URL}/daily_usage?user_id=eq.{safe_uid}&usage_date=eq.{today}",
        headers=_headers,
    )
    rows = resp.json()
    if rows:
        new_count = rows[0]["question_count"] + count
        _supabase_request(
            "patch",
            f"{REST_URL}/daily_usage?user_id=eq.{safe_uid}&usage_date=eq.{today}",
            headers=_headers,
            json={"question_count": new_count},
        )
    else:
        _supabase_request(
            "post",
            f"{REST_URL}/daily_usage",
            headers=_headers,
            json={"user_id": user_id, "usage_date": today, "question_count": count},
        )


def _supabase_get_daily_usage(user_id: str) -> int:  # pragma: no cover
    today = date.today().isoformat()
    safe_uid = _safe_filter_value(user_id)
    resp = _supabase_request(
        "get",
        f"{REST_URL}/daily_usage?user_id=eq.{safe_uid}&usage_date=eq.{today}",
        headers=_headers,
    )
    rows = resp.json()
    return rows[0]["question_count"] if rows else 0


# ========== Helpers ==========

def _row_to_org(row) -> dict:
    """Convert a SQLite Row to an org dict."""
    return {
        "id": row["id"],
        "name": row["name"],
        "invite_code": row["invite_code"],
        "seat_limit": row["seat_limit"],
        "is_active": bool(row["is_active"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
