"""
Integration tests for Free/Pro tier endpoint gating.
"""
import time
import pytest
import jwt
from tests.conftest import _make_token


@pytest.fixture
def org_db():
    import database_org
    database_org.migrate_add_org_tables()
    return database_org


def _make_user_headers(user_id: str) -> dict:
    token = _make_token({"sub": user_id})
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def free_headers():
    """Headers for a free-tier user (no org)."""
    return _make_user_headers("free-user-001")


@pytest.fixture
def pro_headers(org_db):
    """Headers for a pro-tier user (in active org)."""
    org = org_db.create_org("ProOrg", seat_limit=10, created_by="admin")
    org_db.add_member(org["id"], "pro-user-001")
    return _make_user_headers("pro-user-001")


class TestQuizGating:
    def test_free_user_can_quiz(self, client, free_headers, populated_db, org_db):
        resp = client.post("/api/v1/quiz", json={"num_choice": 2, "num_tf": 0}, headers=free_headers)
        assert resp.status_code == 200

    def test_free_user_blocked_after_limit(self, client, populated_db, org_db):
        headers = _make_user_headers("limit-quiz-user")
        # Exhaust daily limit
        org_db.increment_daily_usage("limit-quiz-user", count=5)
        resp = client.post("/api/v1/quiz", json={"num_choice": 1, "num_tf": 0}, headers=headers)
        assert resp.status_code == 403
        assert "limit" in resp.json()["detail"].lower()

    def test_pro_user_unlimited(self, client, pro_headers, populated_db, org_db):
        org_db.increment_daily_usage("pro-user-001", count=100)
        resp = client.post("/api/v1/quiz", json={"num_choice": 2, "num_tf": 0}, headers=pro_headers)
        assert resp.status_code == 200


class TestExamGating:
    def test_free_user_blocked_after_limit(self, client, populated_db, org_db):
        headers = _make_user_headers("limit-exam-user")
        org_db.increment_daily_usage("limit-exam-user", count=5)
        resp = client.post("/api/v1/exam/start", json={"num_choice": 2, "num_tf": 0, "num_multichoice": 0}, headers=headers)
        assert resp.status_code == 403

    def test_pro_user_unlimited(self, client, pro_headers, populated_db, org_db):
        org_db.increment_daily_usage("pro-user-001", count=100)
        resp = client.post("/api/v1/exam/start", json={"num_choice": 2, "num_tf": 0, "num_multichoice": 0}, headers=pro_headers)
        assert resp.status_code == 200


class TestNotebookGating:
    def test_free_user_limited_view(self, client, free_headers, org_db):
        resp = client.get("/api/v1/notebook?limit=50", headers=free_headers)
        assert resp.status_code == 200
        assert resp.json()["limit"] <= 5
        assert resp.json()["tier"] == "free"

    def test_pro_user_full_view(self, client, pro_headers, org_db):
        resp = client.get("/api/v1/notebook?limit=50", headers=pro_headers)
        assert resp.status_code == 200
        assert resp.json()["limit"] == 50
        assert resp.json()["tier"] == "pro"

    def test_free_user_notebook_practice_blocked(self, client, free_headers, org_db):
        resp = client.post("/api/v1/notebook/practice", json={"num_questions": 5}, headers=free_headers)
        assert resp.status_code == 403

    def test_pro_user_notebook_practice_allowed(self, client, pro_headers, org_db):
        # Will get 400 (no questions) but NOT 403
        resp = client.post("/api/v1/notebook/practice", json={"num_questions": 5}, headers=pro_headers)
        assert resp.status_code == 400  # "No questions in notebook", not 403


class TestDashboardGating:
    def test_free_user_summary_allowed(self, client, free_headers, org_db):
        resp = client.get("/api/v1/dashboard/summary", headers=free_headers)
        assert resp.status_code == 200

    def test_free_user_accuracy_trend_blocked(self, client, free_headers, org_db):
        resp = client.get("/api/v1/dashboard/accuracy-trend", headers=free_headers)
        assert resp.status_code == 403

    def test_free_user_volume_blocked(self, client, free_headers, org_db):
        resp = client.get("/api/v1/dashboard/volume", headers=free_headers)
        assert resp.status_code == 403

    def test_free_user_chapter_accuracy_blocked(self, client, free_headers, org_db):
        resp = client.get("/api/v1/dashboard/chapter-accuracy", headers=free_headers)
        assert resp.status_code == 403

    def test_pro_user_all_dashboard(self, client, pro_headers, org_db):
        for endpoint in ["accuracy-trend", "volume", "chapter-accuracy", "summary"]:
            resp = client.get(f"/api/v1/dashboard/{endpoint}", headers=pro_headers)
            assert resp.status_code == 200, f"Failed for {endpoint}"


class TestMyOrgEndpoint:
    def test_free_user_status(self, client, free_headers, org_db):
        resp = client.get("/api/v1/me/org", headers=free_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "free"
        assert data["remaining_questions"] == 5
        assert data["organization"] is None

    def test_pro_user_status(self, client, pro_headers, org_db):
        resp = client.get("/api/v1/me/org", headers=pro_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "pro"
        assert data["remaining_questions"] is None
        assert data["organization"] is not None
