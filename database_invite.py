"""
Database layer for invite codes, pro subscriptions, and daily usage tracking.
Dual-backend: Supabase PostgreSQL (prod) with SQLite fallback (dev).
"""
import logging
import secrets
import sqlite3
import string
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from database import (
    _is_supabase, _supabase_request, _headers, REST_URL,
    _safe_filter_value, _SQLITE_DB, _sqlite_conn,
)

logger = logging.getLogger(__name__)

_CODE_LENGTH = 8
_CODE_CHARS = string.ascii_uppercase + string.digits


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_CHARS) for _ in range(_CODE_LENGTH))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ========== Migration (SQLite only) ==========

def migrate_add_invite_tables():
    if _is_supabase():
        return
    conn = _sqlite_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS invites (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                code          TEXT NOT NULL UNIQUE,
                max_uses      INTEGER NOT NULL DEFAULT 1,
                duration_days INTEGER NOT NULL,
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_by    TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                label         TEXT
            );
            CREATE TABLE IF NOT EXISTS user_pro (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                invite_id    INTEGER NOT NULL REFERENCES invites(id),
                activated_at TEXT NOT NULL,
                expires_at   TEXT NOT NULL,
                UNIQUE(user_id, invite_id)
            );
            CREATE TABLE IF NOT EXISTS daily_usage (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        TEXT NOT NULL,
                usage_date     TEXT NOT NULL,
                question_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, usage_date)
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ========== Invite CRUD ==========

def create_invite(duration_days: int, max_uses: int, created_by: str,
                  label: Optional[str] = None) -> dict:
    if _is_supabase():
        return _sb_create_invite(duration_days, max_uses, created_by, label)
    return _sq_create_invite(duration_days, max_uses, created_by, label)


def get_invite_by_code(code: str) -> Optional[dict]:
    if _is_supabase():
        return _sb_get_invite_by_code(code)
    return _sq_get_invite_by_code(code)


def list_invites() -> list[dict]:
    if _is_supabase():
        return _sb_list_invites()
    return _sq_list_invites()


def deactivate_invite(invite_id: int) -> bool:
    if _is_supabase():
        return _sb_deactivate_invite(invite_id)
    return _sq_deactivate_invite(invite_id)


def get_redemptions(invite_id: int) -> list[dict]:
    if _is_supabase():
        return _sb_get_redemptions(invite_id)
    return _sq_get_redemptions(invite_id)


# ========== Redeem / Pro Status ==========

def redeem_invite(code: str, user_id: str) -> dict:
    if _is_supabase():
        return _sb_redeem_invite(code, user_id)
    return _sq_redeem_invite(code, user_id)


def get_user_pro(user_id: str) -> Optional[dict]:
    """Get active (non-expired) pro status. Returns None if free."""
    if _is_supabase():
        return _sb_get_user_pro(user_id)
    return _sq_get_user_pro(user_id)


def list_pro_users() -> list[dict]:
    """List all user_pro records (active + expired) with invite code."""
    if _is_supabase():
        return _sb_list_pro_users()
    return _sq_list_pro_users()


# ========== Daily Usage ==========

def increment_daily_usage(user_id: str, count: int = 1) -> None:
    if _is_supabase():
        _sb_increment_daily_usage(user_id, count)
    else:
        _sq_increment_daily_usage(user_id, count)


def get_daily_usage(user_id: str) -> int:
    if _is_supabase():
        return _sb_get_daily_usage(user_id)
    return _sq_get_daily_usage(user_id)


def check_daily_limit(user_id: str, limit: int = 5) -> bool:
    return get_daily_usage(user_id) < limit


# ========== SQLite Implementations ==========

def _sq_create_invite(duration_days, max_uses, created_by, label):
    now = _utcnow().isoformat()
    conn = _sqlite_conn()
    try:
        for _ in range(3):
            code = _generate_code()
            try:
                cur = conn.execute(
                    "INSERT INTO invites (code, max_uses, duration_days, is_active, created_by, created_at, label) "
                    "VALUES (?, ?, ?, 1, ?, ?, ?)",
                    (code, max_uses, duration_days, created_by, now, label),
                )
                conn.commit()
                return {
                    "id": cur.lastrowid, "code": code, "max_uses": max_uses,
                    "duration_days": duration_days, "is_active": True,
                    "created_by": created_by, "created_at": now, "label": label,
                    "used_count": 0,
                }
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("Failed to generate unique invite code")
    finally:
        conn.close()


def _sq_get_invite_by_code(code):
    conn = _sqlite_conn()
    try:
        row = conn.execute("SELECT * FROM invites WHERE code = ?", (code,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["is_active"] = bool(d["is_active"])
        cnt = conn.execute(
            "SELECT COUNT(*) FROM user_pro WHERE invite_id = ?", (d["id"],)
        ).fetchone()[0]
        d["used_count"] = cnt
        return d
    finally:
        conn.close()


def _sq_list_invites():
    conn = _sqlite_conn()
    try:
        rows = conn.execute("SELECT * FROM invites ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["is_active"] = bool(d["is_active"])
            cnt = conn.execute(
                "SELECT COUNT(*) FROM user_pro WHERE invite_id = ?", (d["id"],)
            ).fetchone()[0]
            d["used_count"] = cnt
            result.append(d)
        return result
    finally:
        conn.close()


def _sq_deactivate_invite(invite_id):
    conn = _sqlite_conn()
    try:
        cur = conn.execute("UPDATE invites SET is_active = 0 WHERE id = ?", (invite_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _sq_get_redemptions(invite_id):
    conn = _sqlite_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM user_pro WHERE invite_id = ? ORDER BY activated_at DESC",
            (invite_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _sq_redeem_invite(code, user_id):
    conn = _sqlite_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")

        inv = conn.execute("SELECT * FROM invites WHERE code = ?", (code,)).fetchone()
        if not inv:
            raise ValueError("Invalid invite code")
        inv = dict(inv)
        if not inv["is_active"]:
            raise ValueError("This invite code is no longer active")

        cnt = conn.execute(
            "SELECT COUNT(*) FROM user_pro WHERE invite_id = ?", (inv["id"],)
        ).fetchone()[0]
        if cnt >= inv["max_uses"]:
            raise ValueError("This invite code has reached its usage limit")

        existing = conn.execute(
            "SELECT id FROM user_pro WHERE user_id = ? AND invite_id = ?",
            (user_id, inv["id"]),
        ).fetchone()
        if existing:
            raise ValueError("You have already redeemed this code")

        now = _utcnow()
        expires = now + timedelta(days=inv["duration_days"])
        conn.execute(
            "INSERT INTO user_pro (user_id, invite_id, activated_at, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, inv["id"], now.isoformat(), expires.isoformat()),
        )
        conn.commit()
        return {
            "user_id": user_id, "invite_id": inv["id"],
            "activated_at": now.isoformat(), "expires_at": expires.isoformat(),
        }
    except ValueError:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sq_get_user_pro(user_id):
    conn = _sqlite_conn()
    try:
        now = _utcnow().isoformat()
        row = conn.execute(
            "SELECT up.*, i.code FROM user_pro up JOIN invites i ON up.invite_id = i.id "
            "WHERE up.user_id = ? AND up.expires_at > ? ORDER BY up.expires_at DESC LIMIT 1",
            (user_id, now),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _sq_list_pro_users():
    conn = _sqlite_conn()
    try:
        rows = conn.execute(
            "SELECT up.*, i.code, i.label AS invite_label "
            "FROM user_pro up JOIN invites i ON up.invite_id = i.id "
            "ORDER BY up.expires_at DESC"
        ).fetchall()
        now = _utcnow().isoformat()
        result = []
        for r in rows:
            d = dict(r)
            d["is_expired"] = d["expires_at"] <= now
            result.append(d)
        return result
    finally:
        conn.close()


def _sq_increment_daily_usage(user_id, count):
    today = date.today().isoformat()
    conn = _sqlite_conn()
    try:
        row = conn.execute(
            "SELECT question_count FROM daily_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE daily_usage SET question_count = question_count + ? WHERE user_id = ? AND usage_date = ?",
                (count, user_id, today),
            )
        else:
            conn.execute(
                "INSERT INTO daily_usage (user_id, usage_date, question_count) VALUES (?, ?, ?)",
                (user_id, today, count),
            )
        conn.commit()
    finally:
        conn.close()


def _sq_get_daily_usage(user_id):
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

def _sb_create_invite(duration_days, max_uses, created_by, label):
    for _ in range(3):
        code = _generate_code()
        try:
            resp = _supabase_request(
                "post", f"{REST_URL}/invites",
                headers=_headers,
                json={
                    "code": code, "max_uses": max_uses,
                    "duration_days": duration_days, "created_by": created_by,
                    "label": label,
                },
            )
            row = resp.json()[0]
            row["used_count"] = 0
            return row
        except RuntimeError:
            continue
    raise RuntimeError("Failed to generate unique invite code")


def _sb_get_invite_by_code(code):
    safe = _safe_filter_value(code)
    try:
        resp = _supabase_request(
            "get", f"{REST_URL}/invites?code=eq.{safe}&select=*",
            headers=_headers,
        )
    except RuntimeError:
        return None
    rows = resp.json()
    if not rows:
        return None
    inv = rows[0]
    try:
        cnt_resp = _supabase_request(
            "get",
            f"{REST_URL}/user_pro?invite_id=eq.{inv['id']}&select=id",
            headers={**_headers, "Prefer": "count=exact"},
        )
        inv["used_count"] = int(cnt_resp.headers.get("content-range", "*/0").split("/")[-1])
    except RuntimeError:
        inv["used_count"] = 0
    return inv


def _sb_list_invites():
    try:
        resp = _supabase_request(
            "get", f"{REST_URL}/invites?select=*&order=created_at.desc",
            headers=_headers,
        )
    except RuntimeError:
        return []
    invites = resp.json()
    for inv in invites:
        try:
            cnt_resp = _supabase_request(
                "get",
                f"{REST_URL}/user_pro?invite_id=eq.{inv['id']}&select=id",
                headers={**_headers, "Prefer": "count=exact"},
            )
            inv["used_count"] = int(cnt_resp.headers.get("content-range", "*/0").split("/")[-1])
        except RuntimeError:
            inv["used_count"] = 0
    return invites


def _sb_deactivate_invite(invite_id):
    try:
        resp = _supabase_request(
            "patch", f"{REST_URL}/invites?id=eq.{int(invite_id)}",
            headers=_headers,
            json={"is_active": False},
        )
        return bool(resp.json())
    except RuntimeError:
        return False


def _sb_get_redemptions(invite_id):
    try:
        resp = _supabase_request(
            "get",
            f"{REST_URL}/user_pro?invite_id=eq.{int(invite_id)}&select=*&order=activated_at.desc",
            headers=_headers,
        )
        return resp.json()
    except RuntimeError:
        return []


def _sb_redeem_invite(code, user_id):
    inv = _sb_get_invite_by_code(code)
    if not inv:
        raise ValueError("Invalid invite code")
    if not inv.get("is_active", False):
        raise ValueError("This invite code is no longer active")
    if inv.get("used_count", 0) >= inv["max_uses"]:
        raise ValueError("This invite code has reached its usage limit")

    now = _utcnow()
    expires = now + timedelta(days=inv["duration_days"])
    safe_uid = _safe_filter_value(user_id)

    # Check duplicate — do not swallow errors to prevent double redemption
    try:
        dup_resp = _supabase_request(
            "get",
            f"{REST_URL}/user_pro?user_id=eq.{safe_uid}&invite_id=eq.{inv['id']}&select=id",
            headers=_headers,
        )
        if dup_resp.json():
            raise ValueError("You have already redeemed this code")
    except RuntimeError:
        logger.error("Failed to check duplicate redemption for user %s", user_id)
        raise ValueError("Unable to verify redemption status, please try again")

    resp = _supabase_request(
        "post", f"{REST_URL}/user_pro",
        headers=_headers,
        json={
            "user_id": user_id, "invite_id": inv["id"],
            "activated_at": now.isoformat(), "expires_at": expires.isoformat(),
        },
    )
    row = resp.json()[0]
    return row


def _sb_get_user_pro(user_id):
    safe_uid = _safe_filter_value(user_id)
    safe_now = _safe_filter_value(_utcnow().isoformat())
    try:
        resp = _supabase_request(
            "get",
            f"{REST_URL}/user_pro?user_id=eq.{safe_uid}&expires_at=gt.{safe_now}"
            f"&select=*,invites(code)&order=expires_at.desc&limit=1",
            headers=_headers,
        )
    except RuntimeError:
        return None
    rows = resp.json()
    if not rows:
        return None
    row = rows[0]
    inv = row.pop("invites", {}) or {}
    row["code"] = inv.get("code")
    return row


def _sb_list_pro_users():
    try:
        resp = _supabase_request(
            "get",
            f"{REST_URL}/user_pro?select=*,invites(code,label)&order=expires_at.desc",
            headers=_headers,
        )
    except RuntimeError:
        return []
    now = _utcnow().isoformat()
    result = []
    for row in resp.json():
        inv = row.pop("invites", {}) or {}
        row["code"] = inv.get("code")
        row["invite_label"] = inv.get("label")
        row["is_expired"] = row["expires_at"] <= now
        result.append(row)
    return result


def _sb_increment_daily_usage(user_id, count):
    today = date.today().isoformat()
    safe_uid = _safe_filter_value(user_id)
    try:
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
                "post", f"{REST_URL}/daily_usage",
                headers=_headers,
                json={"user_id": user_id, "usage_date": today, "question_count": count},
            )
    except RuntimeError:
        logger.warning("Failed to update daily usage for %s", user_id)


def _sb_get_daily_usage(user_id):
    today = date.today().isoformat()
    safe_uid = _safe_filter_value(user_id)
    try:
        resp = _supabase_request(
            "get",
            f"{REST_URL}/daily_usage?user_id=eq.{safe_uid}&usage_date=eq.{today}",
            headers=_headers,
        )
        rows = resp.json()
        return rows[0]["question_count"] if rows else 0
    except RuntimeError:
        return 0
