"""API endpoint tests for exam result analysis."""


def _create_and_submit_exam(client, auth_headers):
    """Helper: start and submit an exam, return exam_id."""
    start = client.post("/api/v1/exam/start", json={
        "num_choice": 2, "num_tf": 1, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 30,
    }, headers=auth_headers)
    exam = start.json()
    exam_id = exam["exam_id"]

    answers = {str(q["id"]): "A" for q in exam["questions"]}
    client.post(f"/api/v1/exam/{exam_id}/submit", json={
        "answers": answers, "tab_switches": 1,
    }, headers=auth_headers)
    return exam_id


def test_exam_submit_returns_results(client, populated_db, auth_headers):
    """Submit should return detailed per-question results."""
    start = client.post("/api/v1/exam/start", json={
        "num_choice": 2, "num_tf": 0, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 30,
    }, headers=auth_headers)
    exam = start.json()
    exam_id = exam["exam_id"]

    answers = {str(q["id"]): "A" for q in exam["questions"]}
    res = client.post(f"/api/v1/exam/{exam_id}/submit", json={
        "answers": answers, "tab_switches": 0,
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "results" in data
    for r in data["results"]:
        assert "id" in r
        assert "is_correct" in r
        assert "user_answer" in r
        assert "correct_answer" in r
        assert "content" in r
        assert "chapter" in r
        assert "type" in r


def test_exam_results_endpoint(client, populated_db, auth_headers):
    """GET /exam/{id}/results should return detailed results after submit."""
    exam_id = _create_and_submit_exam(client, auth_headers)

    res = client.get(f"/api/v1/exam/{exam_id}/results", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["exam_id"] == exam_id
    assert "score" in data
    assert "total" in data
    assert "percentage" in data
    assert "question_results" in data
    assert "tab_switches" in data


def test_exam_results_before_submit(client, populated_db, auth_headers):
    """Should return 400 if exam not yet submitted."""
    start = client.post("/api/v1/exam/start", json={
        "num_choice": 1, "num_tf": 0, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 30,
    }, headers=auth_headers)
    start_data = start.json()
    assert "exam_id" in start_data, f"Exam start failed: {start_data}"
    exam_id = start_data["exam_id"]

    res = client.get(f"/api/v1/exam/{exam_id}/results", headers=auth_headers)
    assert res.status_code == 400


def test_exam_results_not_found(client, auth_headers):
    """Should return 404 for non-existent exam."""
    res = client.get(
        "/api/v1/exam/00000000-0000-0000-0000-000000000000/results",
        headers=auth_headers,
    )
    assert res.status_code == 404
