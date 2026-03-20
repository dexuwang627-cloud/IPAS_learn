"""API endpoint tests for quiz router."""
import pytest


def test_start_quiz(client, populated_db, auth_headers):
    res = client.post("/api/v1/quiz", json={
        "num_choice": 2, "num_tf": 1, "num_multichoice": 0, "num_scenario": 0,
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert "session_id" in data
    assert "questions" in data
    # Answers should NOT be in the response
    for q in data["questions"]:
        assert "answer" not in q


def test_start_quiz_with_bank_id(client, populated_db, auth_headers):
    res = client.post("/api/v1/quiz", json={
        "num_choice": 2, "num_tf": 0, "num_multichoice": 0,
        "num_scenario": 0, "bank_id": "ipas-netzero-mid",
    }, headers=auth_headers)
    assert res.status_code == 200


def test_check_answers(client, populated_db, auth_headers):
    # Start a quiz first
    start = client.post("/api/v1/quiz", json={
        "num_choice": 1, "num_tf": 1, "num_multichoice": 0, "num_scenario": 0,
    }, headers=auth_headers)
    quiz = start.json()
    questions = quiz["questions"]

    # Submit some answers
    answers = {}
    for q in questions:
        answers[str(q["id"])] = "A"

    res = client.post("/api/v1/quiz/check", json={
        "answers": answers,
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "score" in data
    assert "total" in data
    assert "percentage" in data
    assert "results" in data


def test_check_answers_empty(client, auth_headers):
    res = client.post("/api/v1/quiz/check", json={
        "answers": {},
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["score"] == 0
    assert data["total"] == 0


def test_quiz_requires_auth(client):
    res = client.post("/api/v1/quiz", json={
        "num_choice": 1, "num_tf": 0, "num_multichoice": 0, "num_scenario": 0,
    })
    assert res.status_code in (401, 422)


def test_check_requires_auth(client):
    res = client.post("/api/v1/quiz/check", json={"answers": {"1": "A"}})
    assert res.status_code in (401, 422)
