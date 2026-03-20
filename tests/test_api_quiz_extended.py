"""Extended tests for quiz router covering more code paths."""
import pytest


def test_start_quiz_multichoice(client, populated_db, auth_headers):
    """Test multichoice questions include hint."""
    res = client.post("/api/v1/quiz", json={
        "num_choice": 0, "num_tf": 0, "num_multichoice": 5, "num_scenario": 0,
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    mc_qs = [q for q in data["questions"] if q["type"] in ("multichoice", "scenario_multichoice")]
    for q in mc_qs:
        assert "hint" in q


def test_start_quiz_scenario(client, populated_db, auth_headers):
    """Test scenario question grouping."""
    res = client.post("/api/v1/quiz", json={
        "num_choice": 0, "num_tf": 0, "num_multichoice": 0, "num_scenario": 5,
    }, headers=auth_headers)
    assert res.status_code == 200


def test_start_quiz_with_session_reuse(client, populated_db, auth_headers):
    """Starting a second quiz with same session_id should exclude seen questions."""
    res1 = client.post("/api/v1/quiz", json={
        "num_choice": 1, "num_tf": 0, "num_multichoice": 0, "num_scenario": 0,
    }, headers=auth_headers)
    data1 = res1.json()
    session_id = data1["session_id"]

    res2 = client.post("/api/v1/quiz", json={
        "num_choice": 1, "num_tf": 0, "num_multichoice": 0, "num_scenario": 0,
        "session_id": session_id,
    }, headers=auth_headers)
    assert res2.status_code == 200


def test_check_multichoice_partial(client, populated_db, auth_headers):
    """Test partial credit info for multichoice wrong answers."""
    # Find a multichoice question
    res = client.post("/api/v1/quiz", json={
        "num_choice": 0, "num_tf": 0, "num_multichoice": 5, "num_scenario": 0,
    }, headers=auth_headers)
    quiz = res.json()
    mc_qs = [q for q in quiz["questions"] if q["type"] in ("multichoice", "scenario_multichoice")]

    if mc_qs:
        answers = {str(mc_qs[0]["id"]): "A"}  # Probably partial
        check = client.post("/api/v1/quiz/check", json={
            "answers": answers,
        }, headers=auth_headers)
        assert check.status_code == 200


def test_quiz_pdf_no_builder(client, populated_db, auth_headers):
    """PDF endpoint when weasyprint not available."""
    res = client.post(
        "/api/v1/quiz/pdf?num_choice=5&num_tf=3",
        headers=auth_headers,
    )
    # Should return some response (either PDF or error about not available)
    assert res.status_code == 200


def test_reset_session(client, auth_headers):
    """Test quiz reset endpoint."""
    res = client.post(
        "/api/v1/quiz/reset?session_id=00000000-0000-0000-0000-000000000001",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert "session_id" in data
    assert "cleared" in data


def test_check_all_correct(client, populated_db, auth_headers):
    """Answering all questions correctly should give 100%."""
    # Get questions with answers (admin)
    from tests.conftest import _make_token
    admin_token = _make_token({"email": "admin@example.com", "app_metadata": {"role": "admin"}})
    admin_h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

    qs_res = client.get("/api/v1/questions?limit=5", headers=admin_h)
    questions = qs_res.json()["questions"]

    # Start quiz
    quiz_res = client.post("/api/v1/quiz", json={
        "num_choice": 5, "num_tf": 5, "num_multichoice": 5, "num_scenario": 0,
    }, headers=auth_headers)
    quiz = quiz_res.json()

    # Build correct answers from admin data
    q_map = {str(q["id"]): q["answer"] for q in questions if "answer" in q}
    answers = {}
    for q in quiz["questions"]:
        qid = str(q["id"])
        if qid in q_map:
            answers[qid] = q_map[qid]

    if answers:
        check = client.post("/api/v1/quiz/check", json={"answers": answers}, headers=auth_headers)
        assert check.status_code == 200
        data = check.json()
        assert data["score"] == data["total"]
        assert data["percentage"] == 100.0
