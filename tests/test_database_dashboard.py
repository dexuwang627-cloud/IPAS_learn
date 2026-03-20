"""Unit tests for learning dashboard database layer."""
import sqlite3
from datetime import datetime, timedelta, timezone

import database
from database_notebook import migrate_add_wrong_notebook
from database_dashboard import (
    get_accuracy_trend,
    get_daily_volume,
    get_chapter_accuracy,
    get_dashboard_summary,
    _calculate_streaks,
)

USER_ID = "test-user-00000000-0000-0000-0000-000000000001"


def _insert_history(user_id, entries):
    """Insert quiz_history entries directly for testing."""
    conn = sqlite3.connect(database._SQLITE_DB)
    for e in entries:
        conn.execute("""
            INSERT INTO quiz_history
            (user_id, question_id, question_type, chapter,
             content_preview, is_correct, user_answer, correct_answer, answered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, e.get("question_id", 1), e.get("type", "choice"),
            e.get("chapter", "Climate"), e.get("preview", "test"),
            e["is_correct"], e.get("user_answer", "A"),
            e.get("correct_answer", "B"), e["answered_at"],
        ))
    conn.commit()
    conn.close()


def test_accuracy_trend_daily(populated_db):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _insert_history(USER_ID, [
        {"is_correct": True, "answered_at": f"{today} 10:00:00"},
        {"is_correct": False, "answered_at": f"{today} 11:00:00"},
        {"is_correct": True, "answered_at": f"{today} 12:00:00"},
    ])
    result = get_accuracy_trend(USER_ID, "day", 30)
    assert len(result) >= 1
    day_data = result[-1]
    assert day_data["total"] == 3
    assert day_data["correct"] == 2
    assert day_data["accuracy"] == 66.7


def test_accuracy_trend_weekly(populated_db):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _insert_history(USER_ID, [
        {"is_correct": True, "answered_at": f"{today} 10:00:00"},
        {"is_correct": False, "answered_at": f"{today} 11:00:00"},
    ])
    result = get_accuracy_trend(USER_ID, "week", 30)
    assert len(result) >= 1
    assert "W" in result[0]["date"]


def test_accuracy_trend_empty(populated_db):
    result = get_accuracy_trend(USER_ID, "day", 30)
    assert result == []


def test_daily_volume(populated_db):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    _insert_history(USER_ID, [
        {"is_correct": True, "answered_at": f"{today} 10:00:00"},
        {"is_correct": False, "answered_at": f"{today} 11:00:00"},
        {"is_correct": True, "answered_at": f"{yesterday} 09:00:00"},
    ])
    result = get_daily_volume(USER_ID, 30)
    assert len(result) == 2
    counts = {d["date"]: d["count"] for d in result}
    assert counts[today] == 2
    assert counts[yesterday] == 1


def test_daily_volume_days_filter(populated_db):
    old_date = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _insert_history(USER_ID, [
        {"is_correct": True, "answered_at": f"{old_date} 10:00:00"},
        {"is_correct": True, "answered_at": f"{today} 10:00:00"},
    ])
    result = get_daily_volume(USER_ID, 30)
    dates = [d["date"] for d in result]
    assert old_date not in dates
    assert today in dates


def test_chapter_accuracy(populated_db):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _insert_history(USER_ID, [
        {"is_correct": True, "chapter": "Climate", "answered_at": f"{today} 10:00:00"},
        {"is_correct": False, "chapter": "Climate", "answered_at": f"{today} 11:00:00"},
        {"is_correct": True, "chapter": "Carbon", "answered_at": f"{today} 12:00:00"},
        {"is_correct": True, "chapter": "Carbon", "answered_at": f"{today} 13:00:00"},
    ])
    result = get_chapter_accuracy(USER_ID)
    by_ch = {d["chapter"]: d for d in result}
    assert by_ch["Climate"]["accuracy"] == 50.0
    assert by_ch["Carbon"]["accuracy"] == 100.0


def test_dashboard_summary(populated_db):
    migrate_add_wrong_notebook()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _insert_history(USER_ID, [
        {"is_correct": True, "answered_at": f"{today} 10:00:00"},
        {"is_correct": False, "answered_at": f"{today} 11:00:00"},
    ])
    summary = get_dashboard_summary(USER_ID)
    assert summary["total_answered"] == 2
    assert summary["overall_accuracy"] == 50.0
    assert summary["total_days_active"] == 1
    assert "current_streak" in summary
    assert "best_streak" in summary
    assert "wrong_notebook_count" in summary
    assert "bookmarked_count" in summary


def test_dashboard_summary_streak(populated_db):
    migrate_add_wrong_notebook()
    today = datetime.now(timezone.utc)
    dates = [today - timedelta(days=i) for i in range(3)]  # today, yesterday, 2 days ago
    entries = [
        {"is_correct": True, "answered_at": d.strftime("%Y-%m-%d 10:00:00")}
        for d in dates
    ]
    _insert_history(USER_ID, entries)
    summary = get_dashboard_summary(USER_ID)
    assert summary["current_streak"] == 3
    assert summary["best_streak"] >= 3


def test_calculate_streaks_empty():
    current, best = _calculate_streaks([])
    assert current == 0
    assert best == 0


def test_calculate_streaks_gap():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    # Gap between today and 2 days ago
    current, best = _calculate_streaks([today, two_days_ago, three_days_ago])
    assert current == 1  # only today
    assert best == 2  # 2-day and 3-day ago are consecutive
