"""API endpoint tests for exam router."""
import pytest


def test_start_exam(client, populated_db, auth_headers):
    res = client.post("/api/v1/exam/start", json={
        "num_choice": 2, "num_tf": 1, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 30,
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "exam_id" in data
    assert "duration_min" in data
    assert "started_at" in data
    assert "questions" in data
    # Answers should NOT be in the response
    for q in data["questions"]:
        assert "answer" not in q
        assert "explanation" not in q


def test_submit_exam(client, populated_db, auth_headers):
    # Start exam
    start = client.post("/api/v1/exam/start", json={
        "num_choice": 2, "num_tf": 0, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 60,
    }, headers=auth_headers)
    exam = start.json()
    exam_id = exam["exam_id"]

    # Submit answers (just guess A for everything)
    answers = {str(q["id"]): "A" for q in exam["questions"]}
    res = client.post(f"/api/v1/exam/{exam_id}/submit", json={
        "answers": answers, "tab_switches": 0,
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "score" in data
    assert "total" in data
    assert "percentage" in data
    assert "penalty" in data


def test_submit_exam_double(client, populated_db, auth_headers):
    """Second submit should fail."""
    start = client.post("/api/v1/exam/start", json={
        "num_choice": 1, "num_tf": 0, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 60,
    }, headers=auth_headers)
    exam = start.json()
    exam_id = exam["exam_id"]

    answers = {str(q["id"]): "A" for q in exam["questions"]}
    client.post(f"/api/v1/exam/{exam_id}/submit", json={
        "answers": answers, "tab_switches": 0,
    }, headers=auth_headers)

    # Second submit
    res = client.post(f"/api/v1/exam/{exam_id}/submit", json={
        "answers": answers, "tab_switches": 0,
    }, headers=auth_headers)
    assert res.status_code == 400


def test_tab_switch(client, populated_db, auth_headers):
    start = client.post("/api/v1/exam/start", json={
        "num_choice": 1, "num_tf": 0, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 60,
    }, headers=auth_headers)
    exam_id = start.json()["exam_id"]

    res = client.post(f"/api/v1/exam/{exam_id}/tab-switch", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["tab_switches"] == 1

    res = client.post(f"/api/v1/exam/{exam_id}/tab-switch", headers=auth_headers)
    assert res.json()["tab_switches"] == 2


def test_tab_switch_penalty(client, populated_db, auth_headers):
    """Tab switches should reduce score."""
    start = client.post("/api/v1/exam/start", json={
        "num_choice": 2, "num_tf": 0, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 60,
    }, headers=auth_headers)
    exam = start.json()
    exam_id = exam["exam_id"]

    # Record tab switches
    client.post(f"/api/v1/exam/{exam_id}/tab-switch", headers=auth_headers)
    client.post(f"/api/v1/exam/{exam_id}/tab-switch", headers=auth_headers)

    answers = {str(q["id"]): "A" for q in exam["questions"]}
    res = client.post(f"/api/v1/exam/{exam_id}/submit", json={
        "answers": answers, "tab_switches": 2,
    }, headers=auth_headers)
    data = res.json()
    assert data["tab_switches"] == 2
    assert data["penalty"] == data["base_score"] - data["score"]


def test_exam_history(client, populated_db, auth_headers):
    # Start and submit an exam
    start = client.post("/api/v1/exam/start", json={
        "num_choice": 1, "num_tf": 0, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 30,
    }, headers=auth_headers)
    exam_id = start.json()["exam_id"]
    answers = {str(q["id"]): "A" for q in start.json()["questions"]}
    client.post(f"/api/v1/exam/{exam_id}/submit", json={
        "answers": answers, "tab_switches": 0,
    }, headers=auth_headers)

    res = client.get("/api/v1/exam/history", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "exams" in data
    assert len(data["exams"]) >= 1


def test_exam_requires_auth(client):
    res = client.post("/api/v1/exam/start", json={
        "num_choice": 1, "num_tf": 0, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 30,
    })
    assert res.status_code in (401, 422)


def test_exam_not_found(client, auth_headers):
    res = client.post(
        "/api/v1/exam/00000000-0000-0000-0000-000000000000/submit",
        json={"answers": {}, "tab_switches": 0},
        headers=auth_headers,
    )
    assert res.status_code == 404
