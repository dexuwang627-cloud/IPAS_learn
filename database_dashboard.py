"""
Database layer for learning dashboard aggregation queries.
Follows the same dual-backend pattern as database.py.
"""
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from database import (
    _is_supabase, _supabase_request, _headers, REST_URL,
    _safe_filter_value, _SQLITE_DB,
)

logger = logging.getLogger(__name__)


# ========== Public API ==========

def get_accuracy_trend(
    user_id: str, granularity: str = "day", days: int = 30,
) -> list[dict]:
    """Get accuracy trend over time. Returns list of {date, total, correct, accuracy}."""
    if not _is_supabase():
        return _sqlite_get_accuracy_trend(user_id, granularity, days)
    return _supabase_get_accuracy_trend(user_id, granularity, days)


def get_daily_volume(user_id: str, days: int = 30) -> list[dict]:
    """Get daily practice volume. Returns list of {date, count}."""
    if not _is_supabase():
        return _sqlite_get_daily_volume(user_id, days)
    return _supabase_get_daily_volume(user_id, days)


def get_chapter_accuracy(user_id: str) -> list[dict]:
    """Get per-chapter accuracy. Returns list of {chapter, total, correct, accuracy}."""
    if not _is_supabase():
        return _sqlite_get_chapter_accuracy(user_id)
    return _supabase_get_chapter_accuracy(user_id)


def get_dashboard_summary(user_id: str) -> dict:
    """Get combined dashboard summary stats."""
    if not _is_supabase():
        return _sqlite_get_dashboard_summary(user_id)
    return _supabase_get_dashboard_summary(user_id)


# ========== SQLite Implementation ==========

def _sqlite_get_accuracy_trend(
    user_id: str, granularity: str, days: int,
) -> list[dict]:
    conn = sqlite3.connect(_SQLITE_DB)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    if granularity == "week":
        date_expr = "strftime('%Y-W%W', answered_at)"
    else:
        date_expr = "date(answered_at)"

    rows = conn.execute(f"""
        SELECT {date_expr} as period,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct
        FROM quiz_history
        WHERE user_id = ? AND answered_at >= ?
        GROUP BY period
        ORDER BY period ASC
    """, (user_id, cutoff)).fetchall()
    conn.close()

    return [
        {
            "date": r[0],
            "total": r[1],
            "correct": r[2],
            "accuracy": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0,
        }
        for r in rows
    ]


def _sqlite_get_daily_volume(user_id: str, days: int) -> list[dict]:
    conn = sqlite3.connect(_SQLITE_DB)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT date(answered_at) as day, COUNT(*) as count
        FROM quiz_history
        WHERE user_id = ? AND answered_at >= ?
        GROUP BY day
        ORDER BY day ASC
    """, (user_id, cutoff)).fetchall()
    conn.close()
    return [{"date": r[0], "count": r[1]} for r in rows]


def _sqlite_get_chapter_accuracy(user_id: str) -> list[dict]:
    conn = sqlite3.connect(_SQLITE_DB)
    rows = conn.execute("""
        SELECT chapter,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct
        FROM quiz_history
        WHERE user_id = ? AND chapter IS NOT NULL
        GROUP BY chapter
        ORDER BY chapter ASC
    """, (user_id,)).fetchall()
    conn.close()
    return [
        {
            "chapter": r[0],
            "total": r[1],
            "correct": r[2],
            "accuracy": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0,
        }
        for r in rows
    ]


def _sqlite_get_dashboard_summary(user_id: str) -> dict:
    conn = sqlite3.connect(_SQLITE_DB)

    # Total answered and accuracy
    row = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct
        FROM quiz_history WHERE user_id = ?
    """, (user_id,)).fetchone()
    total_answered = row[0]
    total_correct = row[1] or 0

    # Active days
    active_days = conn.execute("""
        SELECT COUNT(DISTINCT date(answered_at))
        FROM quiz_history WHERE user_id = ?
    """, (user_id,)).fetchone()[0]

    # Daily dates for streak calculation
    date_rows = conn.execute("""
        SELECT DISTINCT date(answered_at) as day
        FROM quiz_history WHERE user_id = ?
        ORDER BY day DESC
    """, (user_id,)).fetchall()

    # Notebook stats (may not exist yet)
    try:
        notebook_total = conn.execute(
            "SELECT COUNT(*) FROM wrong_notebook WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        notebook_bookmarked = conn.execute(
            "SELECT COUNT(*) FROM wrong_notebook "
            "WHERE user_id = ? AND bookmarked = 1",
            (user_id,),
        ).fetchone()[0]
    except sqlite3.OperationalError:
        notebook_total = 0
        notebook_bookmarked = 0

    conn.close()

    # Calculate streaks
    current_streak, best_streak = _calculate_streaks(
        [r[0] for r in date_rows],
    )

    return {
        "total_answered": total_answered,
        "overall_accuracy": (
            round(total_correct / total_answered * 100, 1)
            if total_answered > 0 else 0
        ),
        "total_days_active": active_days,
        "current_streak": current_streak,
        "best_streak": best_streak,
        "wrong_notebook_count": notebook_total,
        "bookmarked_count": notebook_bookmarked,
    }


def _calculate_streaks(dates_desc: list[str]) -> tuple[int, int]:
    """Calculate current and best streak from descending date strings.
    Returns (current_streak, best_streak).
    """
    if not dates_desc:
        return 0, 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parsed = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates_desc]

    # Current streak: must include today or yesterday
    current = 0
    check_date = datetime.strptime(today, "%Y-%m-%d").date()
    if parsed and (parsed[0] == check_date or parsed[0] == check_date - timedelta(days=1)):
        for d in parsed:
            if d == check_date:
                current += 1
                check_date -= timedelta(days=1)
            else:
                break

    # Best streak
    best = 1 if parsed else 0
    run = 1
    for i in range(1, len(parsed)):
        if parsed[i] == parsed[i - 1] - timedelta(days=1):
            run += 1
            best = max(best, run)
        else:
            run = 1

    return current, best


# ========== Supabase Implementation ==========

def _supabase_get_accuracy_trend(
    user_id: str, granularity: str, days: int,
) -> list[dict]:  # pragma: no cover
    """Fetch quiz_history and aggregate in Python (PostgREST lacks GROUP BY)."""
    safe_uid = _safe_filter_value(user_id)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    url = (
        f"{REST_URL}/quiz_history"
        f"?user_id=eq.{safe_uid}&answered_at=gte.{quote(cutoff, safe='')}"
        f"&select=answered_at,is_correct&order=answered_at.asc"
    )
    resp = _supabase_request("get", url, headers=_headers)
    rows = resp.json()

    # Aggregate in Python
    buckets: dict[str, dict] = {}
    for r in rows:
        dt = r["answered_at"][:10]  # YYYY-MM-DD
        if granularity == "week":
            d = datetime.strptime(dt, "%Y-%m-%d")
            dt = f"{d.year}-W{d.strftime('%W')}"
        if dt not in buckets:
            buckets[dt] = {"total": 0, "correct": 0}
        buckets[dt]["total"] += 1
        if r["is_correct"]:
            buckets[dt]["correct"] += 1

    return [
        {
            "date": k,
            "total": v["total"],
            "correct": v["correct"],
            "accuracy": round(v["correct"] / v["total"] * 100, 1),
        }
        for k, v in sorted(buckets.items())
    ]


def _supabase_get_daily_volume(
    user_id: str, days: int,
) -> list[dict]:  # pragma: no cover
    safe_uid = _safe_filter_value(user_id)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    url = (
        f"{REST_URL}/quiz_history"
        f"?user_id=eq.{safe_uid}&answered_at=gte.{quote(cutoff, safe='')}"
        f"&select=answered_at&order=answered_at.asc"
    )
    resp = _supabase_request("get", url, headers=_headers)
    counts: dict[str, int] = {}
    for r in resp.json():
        day = r["answered_at"][:10]
        counts[day] = counts.get(day, 0) + 1
    return [{"date": k, "count": v} for k, v in sorted(counts.items())]


def _supabase_get_chapter_accuracy(user_id: str) -> list[dict]:  # pragma: no cover
    safe_uid = _safe_filter_value(user_id)
    url = (
        f"{REST_URL}/quiz_history"
        f"?user_id=eq.{safe_uid}&chapter=not.is.null"
        f"&select=chapter,is_correct"
    )
    resp = _supabase_request("get", url, headers=_headers)
    chapters: dict[str, dict] = {}
    for r in resp.json():
        ch = r["chapter"]
        if ch not in chapters:
            chapters[ch] = {"total": 0, "correct": 0}
        chapters[ch]["total"] += 1
        if r["is_correct"]:
            chapters[ch]["correct"] += 1

    return [
        {
            "chapter": ch,
            "total": v["total"],
            "correct": v["correct"],
            "accuracy": round(v["correct"] / v["total"] * 100, 1),
        }
        for ch, v in sorted(chapters.items())
    ]


def _supabase_get_dashboard_summary(user_id: str) -> dict:  # pragma: no cover
    volume = _supabase_get_daily_volume(user_id, days=365)
    total_answered = sum(d["count"] for d in volume)

    safe_uid = _safe_filter_value(user_id)
    correct_resp = _supabase_request("get", (
        f"{REST_URL}/quiz_history"
        f"?user_id=eq.{safe_uid}&is_correct=eq.true"
        f"&select=id"
    ), headers={**_headers, "Prefer": "count=exact"})
    total_correct = int(
        correct_resp.headers.get("content-range", "0/0").split("/")[-1] or 0
    )

    dates_desc = sorted([d["date"] for d in volume], reverse=True)
    current_streak, best_streak = _calculate_streaks(dates_desc)

    return {
        "total_answered": total_answered,
        "overall_accuracy": (
            round(total_correct / total_answered * 100, 1)
            if total_answered > 0 else 0
        ),
        "total_days_active": len(volume),
        "current_streak": current_streak,
        "best_streak": best_streak,
        "wrong_notebook_count": 0,
        "bookmarked_count": 0,
    }
