"""API endpoint tests for weakness practice mode."""
import pytest


def _build_quiz_history(client, auth_headers, populated_db):
    """Helper: do a quiz and check answers to build history."""
    # Start a practice quiz
    res = client.post("/api/v1/quiz", json={
        "num_choice": 2, "num_tf": 1, "num_multichoice": 0,
        "num_scenario": 0,
    }, headers=auth_headers)
    data = res.json()
    session_id = data["session_id"]

    # Submit wrong answers to build weakness data
    answers = {}
    for q in data["questions"]:
        answers[str(q["id"])] = "Z"  # wrong answer
    client.post("/api/v1/quiz/check", json={
        "session_id": session_id,
        "answers": answers,
    }, headers=auth_headers)


def test_weakness_quiz_no_history(client, populated_db, auth_headers):
    """Should return 400 if no quiz history exists."""
    res = client.post("/api/v1/quiz/weakness", json={
        "num_questions": 5,
    }, headers=auth_headers)
    assert res.status_code == 400
    assert "No quiz history" in res.json()["detail"]


def test_weakness_quiz_with_history(client, populated_db, auth_headers):
    """After building history, weakness quiz should return questions."""
    _build_quiz_history(client, auth_headers, populated_db)

    res = client.post("/api/v1/quiz/weakness", json={
        "num_questions": 5,
        "num_weak_chapters": 3,
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "questions" in data
    assert "weak_chapters" in data
    assert "session_id" in data
    assert data["total"] >= 1
    # Answers should be stripped
    for q in data["questions"]:
        assert "answer" not in q


def test_weakness_quiz_requires_auth(client, populated_db):
    """Should require authentication."""
    res = client.post("/api/v1/quiz/weakness", json={
        "num_questions": 5,
    })
    assert res.status_code in (401, 422)
