"""Tests for database module (SQLite fallback)."""
import pytest
from database import (
    insert_question, get_questions, get_chapters, get_stats,
    get_questions_by_ids, delete_question,
    save_history_batch, get_history, get_weakness_stats, clear_history,
    create_exam_session, get_exam_session, submit_exam_session,
    increment_tab_switches, get_exam_history,
)


def _sample_q(**overrides):
    q = {
        "chapter": "Climate",
        "chapter_group": "Climate",
        "source_file": "01.pdf",
        "type": "choice",
        "content": "Test question",
        "option_a": "A", "option_b": "B", "option_c": "C", "option_d": "D",
        "answer": "A",
        "difficulty": 1,
    }
    q.update(overrides)
    return q


# ========== Questions ==========

def test_insert_and_get():
    qid = insert_question(_sample_q())
    assert isinstance(qid, int)
    rows = get_questions()
    assert any(r["id"] == qid for r in rows)


def test_get_by_ids():
    id1 = insert_question(_sample_q(content="Q1"))
    id2 = insert_question(_sample_q(content="Q2"))
    rows = get_questions_by_ids([id1, id2])
    assert len(rows) == 2


def test_get_chapters():
    insert_question(_sample_q(chapter_group="Carbon"))
    chapters = get_chapters()
    assert "Carbon" in chapters


def test_get_stats():
    insert_question(_sample_q())
    stats = get_stats()
    assert stats["total"] >= 1
    assert "by_chapter" in stats
    assert "by_type" in stats


def test_filter_by_type():
    insert_question(_sample_q(type="truefalse", option_a=None, option_b=None,
                               option_c=None, option_d=None, answer="T"))
    rows = get_questions(q_type="truefalse")
    assert all(r["type"] == "truefalse" for r in rows)


def test_filter_by_difficulty():
    insert_question(_sample_q(difficulty=3))
    rows = get_questions(difficulty=3)
    assert all(r["difficulty"] == 3 for r in rows)


def test_filter_by_bank_id():
    insert_question(_sample_q(bank_id="test-bank"))
    rows = get_questions(bank_id="test-bank")
    assert all(r["bank_id"] == "test-bank" for r in rows)


def test_delete():
    qid = insert_question(_sample_q())
    delete_question(qid)
    rows = get_questions_by_ids([qid])
    assert len(rows) == 0


def test_explanation():
    qid = insert_question(_sample_q(explanation="Because X"))
    rows = get_questions_by_ids([qid])
    assert rows[0]["explanation"] == "Because X"


# ========== Quiz History ==========

def test_save_and_get_history():
    entries = [
        {"question_id": 1, "question_type": "choice", "chapter": "Climate",
         "content_preview": "Q1", "is_correct": True, "user_answer": "A",
         "correct_answer": "A"},
        {"question_id": 2, "question_type": "choice", "chapter": "Carbon",
         "content_preview": "Q2", "is_correct": False, "user_answer": "B",
         "correct_answer": "A"},
    ]
    count = save_history_batch("user1", entries)
    assert count == 2

    history = get_history("user1", limit=10, offset=0)
    assert len(history) >= 2


def test_weakness_stats():
    entries = [
        {"question_id": 1, "question_type": "choice", "chapter": "Climate",
         "is_correct": True, "user_answer": "A", "correct_answer": "A"},
        {"question_id": 2, "question_type": "choice", "chapter": "Climate",
         "is_correct": False, "user_answer": "B", "correct_answer": "A"},
    ]
    save_history_batch("user2", entries)
    stats = get_weakness_stats("user2")
    assert len(stats) >= 1
    climate = next((s for s in stats if s["chapter"] == "Climate"), None)
    assert climate is not None
    assert climate["total"] == 2
    assert climate["correct"] == 1


def test_clear_history():
    save_history_batch("user3", [
        {"question_id": 1, "question_type": "choice",
         "is_correct": True, "user_answer": "A"},
    ])
    cleared = clear_history("user3")
    assert cleared >= 1
    history = get_history("user3", limit=10, offset=0)
    assert len(history) == 0


# ========== Exam Sessions ==========

def test_create_and_get_exam():
    session = create_exam_session(
        user_id="user1", bank_id="test", question_ids=[1, 2, 3],
        shuffle_map={"1": {"position": 0}}, duration_min=60,
    )
    assert session["status"] == "active"
    assert "id" in session

    fetched = get_exam_session(session["id"], "user1")
    assert fetched is not None
    assert fetched["question_ids"] == [1, 2, 3]


def test_submit_exam():
    session = create_exam_session(
        user_id="user1", bank_id="test", question_ids=[1],
        shuffle_map={}, duration_min=30,
    )
    result = submit_exam_session(session["id"], "user1", score=1, total=1, tab_switches=0)
    assert result["status"] == "submitted"


def test_increment_tab_switches():
    session = create_exam_session(
        user_id="user1", bank_id="test", question_ids=[1],
        shuffle_map={}, duration_min=30,
    )
    count1 = increment_tab_switches(session["id"], "user1")
    assert count1 == 1
    count2 = increment_tab_switches(session["id"], "user1")
    assert count2 == 2


def test_exam_history():
    session = create_exam_session(
        user_id="user4", bank_id="test", question_ids=[1],
        shuffle_map={}, duration_min=30,
    )
    submit_exam_session(session["id"], "user4", score=1, total=1, tab_switches=0)

    history = get_exam_history("user4", limit=10, offset=0)
    assert len(history) >= 1
    assert history[0]["status"] == "submitted"
