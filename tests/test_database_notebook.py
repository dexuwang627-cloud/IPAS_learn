"""Unit tests for wrong answer notebook database layer."""
from database_notebook import (
    migrate_add_wrong_notebook,
    upsert_wrong_answers,
    toggle_bookmark,
    get_notebook_entries,
    get_notebook_stats,
    get_notebook_question_ids,
    remove_notebook_entry,
)


def test_migrate_creates_table(populated_db):
    """Migration should create wrong_notebook table."""
    import sqlite3
    from database import _SQLITE_DB
    migrate_add_wrong_notebook()
    conn = sqlite3.connect(_SQLITE_DB)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='wrong_notebook'"
    ).fetchall()
    conn.close()
    assert len(tables) == 1


def test_upsert_wrong_answers_new(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    count = upsert_wrong_answers(user_id, [populated_db[0]], "quiz")
    assert count == 1
    items, total = get_notebook_entries(user_id)
    assert total == 1
    assert items[0]["wrong_count"] == 1
    assert items[0]["source"] == "quiz"


def test_upsert_wrong_answers_increment(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, [populated_db[0]], "quiz")
    upsert_wrong_answers(user_id, [populated_db[0]], "quiz")
    items, _ = get_notebook_entries(user_id)
    assert items[0]["wrong_count"] == 2


def test_upsert_multiple_questions(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    count = upsert_wrong_answers(user_id, populated_db[:3], "exam")
    assert count == 3
    _, total = get_notebook_entries(user_id)
    assert total == 3


def test_toggle_bookmark_on(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, [populated_db[0]], "quiz")
    result = toggle_bookmark(user_id, populated_db[0])
    assert result["bookmarked"] is True


def test_toggle_bookmark_off(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, [populated_db[0]], "quiz")
    toggle_bookmark(user_id, populated_db[0])  # on
    result = toggle_bookmark(user_id, populated_db[0])  # off
    assert result["bookmarked"] is False


def test_toggle_bookmark_creates_entry(populated_db):
    """Bookmarking a question with no wrong record should create new entry."""
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    result = toggle_bookmark(user_id, populated_db[0])
    assert result["bookmarked"] is True
    items, total = get_notebook_entries(user_id)
    assert total == 1
    assert items[0]["wrong_count"] == 0
    assert items[0]["source"] == "bookmark"


def test_get_entries_filter_bookmarked(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, populated_db[:2], "quiz")
    toggle_bookmark(user_id, populated_db[0])
    items, total = get_notebook_entries(user_id, filter_type="bookmarked")
    assert total == 1
    assert items[0]["bookmarked"] is True


def test_get_entries_filter_source(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, [populated_db[0]], "quiz")
    upsert_wrong_answers(user_id, [populated_db[1]], "exam")
    items, total = get_notebook_entries(user_id, filter_type="exam")
    assert total == 1
    assert items[0]["source"] == "exam"


def test_get_entries_sort_frequency(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, [populated_db[0]], "quiz")
    upsert_wrong_answers(user_id, [populated_db[0]], "quiz")  # count=2
    upsert_wrong_answers(user_id, [populated_db[1]], "quiz")  # count=1
    items, _ = get_notebook_entries(user_id, sort="frequency")
    assert items[0]["wrong_count"] >= items[1]["wrong_count"]


def test_get_entries_pagination(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, populated_db[:3], "quiz")
    items, total = get_notebook_entries(user_id, limit=1, offset=0)
    assert total == 3
    assert len(items) == 1


def test_get_entries_has_question_data(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, [populated_db[0]], "quiz")
    items, _ = get_notebook_entries(user_id)
    q = items[0]["question"]
    assert q["content"] is not None
    assert q["type"] is not None
    assert q["answer"] is not None


def test_get_notebook_stats(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, populated_db[:2], "quiz")
    upsert_wrong_answers(user_id, [populated_db[2]], "exam")
    toggle_bookmark(user_id, populated_db[0])
    stats = get_notebook_stats(user_id)
    assert stats["total"] == 3
    assert stats["bookmarked"] == 1
    assert stats["by_source"]["quiz"] == 2
    assert stats["by_source"]["exam"] == 1


def test_get_notebook_question_ids(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, populated_db[:3], "quiz")
    ids = get_notebook_question_ids(user_id)
    assert len(ids) == 3
    assert all(isinstance(i, int) for i in ids)


def test_remove_notebook_entry(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    upsert_wrong_answers(user_id, [populated_db[0]], "quiz")
    assert remove_notebook_entry(user_id, populated_db[0]) is True
    _, total = get_notebook_entries(user_id)
    assert total == 0


def test_remove_nonexistent(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    assert remove_notebook_entry(user_id, 99999) is False


def test_upsert_empty_list(populated_db):
    migrate_add_wrong_notebook()
    user_id = "test-user-00000000-0000-0000-0000-000000000001"
    assert upsert_wrong_answers(user_id, [], "quiz") == 0
