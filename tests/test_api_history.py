"""API endpoint tests for history router."""
import pytest


def test_save_history(client, auth_headers):
    res = client.post("/api/v1/history", json={
        "results": [
            {
                "question_id": 1, "question_type": "choice",
                "chapter": "Climate", "content_preview": "Test Q",
                "is_correct": True, "user_answer": "A", "correct_answer": "A",
            },
            {
                "question_id": 2, "question_type": "truefalse",
                "chapter": "Carbon", "content_preview": "Test Q2",
                "is_correct": False, "user_answer": "T", "correct_answer": "F",
            },
        ]
    }, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["saved"] == 2


def test_save_history_invalid_type(client, auth_headers):
    res = client.post("/api/v1/history", json={
        "results": [
            {
                "question_id": 1, "question_type": "invalid_type",
                "is_correct": True, "user_answer": "A",
            },
        ]
    }, headers=auth_headers)
    assert res.status_code == 400


def test_get_history(client, auth_headers):
    # Save some history first
    client.post("/api/v1/history", json={
        "results": [
            {
                "question_id": 1, "question_type": "choice",
                "is_correct": True, "user_answer": "A",
            },
        ]
    }, headers=auth_headers)

    res = client.get("/api/v1/history?limit=10", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "history" in data
    assert len(data["history"]) >= 1


def test_get_weakness_stats(client, auth_headers):
    # Save history with chapter info
    client.post("/api/v1/history", json={
        "results": [
            {"question_id": 1, "question_type": "choice", "chapter": "Climate",
             "is_correct": True, "user_answer": "A"},
            {"question_id": 2, "question_type": "choice", "chapter": "Climate",
             "is_correct": False, "user_answer": "B"},
            {"question_id": 3, "question_type": "choice", "chapter": "Carbon",
             "is_correct": True, "user_answer": "A"},
        ]
    }, headers=auth_headers)

    res = client.get("/api/v1/history/weakness", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "stats" in data


def test_clear_history(client, auth_headers):
    client.post("/api/v1/history", json={
        "results": [
            {"question_id": 1, "question_type": "choice",
             "is_correct": True, "user_answer": "A"},
        ]
    }, headers=auth_headers)

    res = client.delete("/api/v1/history", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["cleared"] >= 1


def test_history_requires_auth(client):
    res = client.get("/api/v1/history")
    assert res.status_code in (401, 422)

    res = client.post("/api/v1/history", json={"results": []})
    assert res.status_code in (401, 422)
