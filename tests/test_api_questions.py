"""API endpoint tests for questions router."""
import pytest


def test_get_chapters(client, populated_db):
    res = client.get("/api/v1/chapters")
    assert res.status_code == 200
    data = res.json()
    assert "chapters" in data
    assert isinstance(data["chapters"], list)


def test_get_stats(client, populated_db):
    res = client.get("/api/v1/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert data["total"] >= 5


def test_get_questions_no_auth(client, populated_db):
    """Non-authenticated users should not see answers."""
    res = client.get("/api/v1/questions?limit=5")
    assert res.status_code == 200
    data = res.json()
    for q in data["questions"]:
        assert "answer" not in q
        assert "explanation" not in q


def test_get_questions_admin(client, populated_db, admin_headers):
    """Admin users should see answers."""
    res = client.get("/api/v1/questions?limit=5", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["questions"]) > 0
    assert "answer" in data["questions"][0]


def test_get_questions_with_filters(client, populated_db, auth_headers):
    res = client.get("/api/v1/questions?q_type=choice&difficulty=1&limit=10", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    for q in data["questions"]:
        assert q["type"] == "choice"
        assert q["difficulty"] == 1


def test_get_questions_with_bank_id(client, populated_db, auth_headers):
    res = client.get("/api/v1/questions?bank_id=ipas-netzero-mid&limit=5", headers=auth_headers)
    assert res.status_code == 200


def test_delete_question_admin(client, populated_db, admin_headers):
    qid = populated_db[0]
    res = client.delete(f"/api/v1/questions/{qid}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_delete_question_non_admin(client, populated_db, auth_headers):
    qid = populated_db[0]
    res = client.delete(f"/api/v1/questions/{qid}", headers=auth_headers)
    assert res.status_code == 403


def test_delete_question_no_auth(client, populated_db):
    qid = populated_db[0]
    res = client.delete(f"/api/v1/questions/{qid}")
    assert res.status_code in (401, 422)


def test_deprecated_api_still_works(client, populated_db):
    """Old /api/ paths should still work."""
    res = client.get("/api/chapters")
    assert res.status_code == 200
    assert "chapters" in res.json()
