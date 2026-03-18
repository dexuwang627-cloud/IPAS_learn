"""API endpoint tests for wrong answer notebook."""


def _do_quiz_with_wrong_answers(client, auth_headers):
    """Start a quiz and submit wrong answers to populate notebook."""
    res = client.post("/api/v1/quiz", json={
        "num_choice": 2, "num_tf": 1, "num_multichoice": 0,
        "num_scenario": 0,
    }, headers=auth_headers)
    data = res.json()
    # Answer everything wrong
    answers = {str(q["id"]): "Z" for q in data["questions"]}
    client.post("/api/v1/quiz/check", json={
        "session_id": data["session_id"],
        "answers": answers,
    }, headers=auth_headers)
    return [q["id"] for q in data["questions"]]


def test_notebook_empty(client, populated_db, auth_headers):
    res = client.get("/api/v1/notebook", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_notebook_auto_collect_from_quiz(client, populated_db, auth_headers):
    question_ids = _do_quiz_with_wrong_answers(client, auth_headers)
    res = client.get("/api/v1/notebook", headers=auth_headers)
    data = res.json()
    assert data["total"] >= 1
    notebook_qids = [item["question_id"] for item in data["items"]]
    for qid in question_ids:
        assert qid in notebook_qids


def test_notebook_auto_collect_from_exam(client, populated_db, auth_headers):
    start = client.post("/api/v1/exam/start", json={
        "num_choice": 2, "num_tf": 0, "num_multichoice": 0,
        "num_scenario": 0, "duration_min": 60,
    }, headers=auth_headers)
    exam = start.json()
    answers = {str(q["id"]): "Z" for q in exam["questions"]}
    client.post(f"/api/v1/exam/{exam['exam_id']}/submit", json={
        "answers": answers, "tab_switches": 0,
    }, headers=auth_headers)

    res = client.get("/api/v1/notebook", headers=auth_headers)
    data = res.json()
    assert data["total"] >= 1


def test_bookmark_toggle(client, populated_db, auth_headers):
    qid = populated_db[0]
    res = client.post(f"/api/v1/notebook/{qid}/bookmark", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["bookmarked"] is True

    res = client.post(f"/api/v1/notebook/{qid}/bookmark", headers=auth_headers)
    assert res.json()["bookmarked"] is False


def test_bookmark_nonexistent(client, auth_headers):
    res = client.post("/api/v1/notebook/999999/bookmark", headers=auth_headers)
    assert res.status_code == 404


def test_delete_notebook_entry(client, populated_db, auth_headers):
    _do_quiz_with_wrong_answers(client, auth_headers)
    # Get first entry
    items = client.get("/api/v1/notebook", headers=auth_headers).json()["items"]
    qid = items[0]["question_id"]

    res = client.delete(f"/api/v1/notebook/{qid}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["deleted"] is True


def test_notebook_practice(client, populated_db, auth_headers):
    _do_quiz_with_wrong_answers(client, auth_headers)
    res = client.post("/api/v1/notebook/practice", json={
        "num_questions": 5,
    }, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["source"] == "notebook"
    assert data["total"] >= 1
    # Answers should be stripped
    for q in data["questions"]:
        assert "answer" not in q
        assert "explanation" not in q


def test_notebook_practice_empty(client, populated_db, auth_headers):
    res = client.post("/api/v1/notebook/practice", json={
        "num_questions": 5,
    }, headers=auth_headers)
    assert res.status_code == 400


def test_notebook_stats(client, populated_db, auth_headers):
    _do_quiz_with_wrong_answers(client, auth_headers)
    res = client.get("/api/v1/notebook/stats", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert "bookmarked" in data
    assert "by_source" in data


def test_notebook_filter_bookmarked(client, populated_db, auth_headers):
    _do_quiz_with_wrong_answers(client, auth_headers)
    items = client.get("/api/v1/notebook", headers=auth_headers).json()["items"]
    qid = items[0]["question_id"]
    client.post(f"/api/v1/notebook/{qid}/bookmark", headers=auth_headers)

    res = client.get("/api/v1/notebook?filter=bookmarked", headers=auth_headers)
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["bookmarked"] is True


def test_notebook_requires_auth(client):
    res = client.get("/api/v1/notebook")
    assert res.status_code in (401, 422)
