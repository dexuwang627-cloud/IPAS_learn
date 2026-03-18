"""
API tests for user org endpoints -- join, leave, status.
"""
import pytest
from tests.conftest import _make_token


@pytest.fixture
def org_db():
    import database_org
    database_org.migrate_add_org_tables()
    return database_org


@pytest.fixture
def org_with_code(org_db):
    """Create an org and return its invite code."""
    org = org_db.create_org("TestUnion", seat_limit=5, created_by="admin")
    return org


class TestJoinOrg:
    def test_join_with_valid_code(self, client, auth_headers, org_with_code):
        code = org_with_code["invite_code"]
        resp = client.post("/api/v1/me/org/join", json={"invite_code": code}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["org_name"] == "TestUnion"

    def test_join_invalid_code(self, client, auth_headers, org_with_code):
        resp = client.post("/api/v1/me/org/join", json={"invite_code": "ZZZZZZZZ"}, headers=auth_headers)
        assert resp.status_code == 404

    def test_join_already_in_org(self, client, auth_headers, org_with_code, org_db):
        code = org_with_code["invite_code"]
        # Join once
        client.post("/api/v1/me/org/join", json={"invite_code": code}, headers=auth_headers)
        # Try to join again (different org or same)
        org2 = org_db.create_org("Other", seat_limit=5, created_by="admin")
        resp = client.post("/api/v1/me/org/join", json={"invite_code": org2["invite_code"]}, headers=auth_headers)
        assert resp.status_code == 409

    def test_join_seats_full(self, client, org_db):
        org = org_db.create_org("FullOrg", seat_limit=1, created_by="admin")
        org_db.add_member(org["id"], "other-user")
        # Now try to join as test user
        token = _make_token({"sub": "joiner"})
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = client.post("/api/v1/me/org/join", json={"invite_code": org["invite_code"]}, headers=headers)
        assert resp.status_code == 400
        assert "seat" in resp.json()["detail"].lower() or "Seat" in resp.json()["detail"]

    def test_join_bad_code_format(self, client, auth_headers, org_with_code):
        resp = client.post("/api/v1/me/org/join", json={"invite_code": "short"}, headers=auth_headers)
        assert resp.status_code == 422


class TestLeaveOrg:
    def test_leave_org(self, client, auth_headers, org_with_code):
        code = org_with_code["invite_code"]
        client.post("/api/v1/me/org/join", json={"invite_code": code}, headers=auth_headers)
        resp = client.post("/api/v1/me/org/leave", headers=auth_headers)
        assert resp.status_code == 200

    def test_leave_not_in_org(self, client, auth_headers, org_with_code):
        resp = client.post("/api/v1/me/org/leave", headers=auth_headers)
        assert resp.status_code == 404


class TestGetMyOrg:
    def test_free_user(self, client, auth_headers, org_with_code):
        resp = client.get("/api/v1/me/org", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "free"
        assert data["remaining_questions"] == 5
        assert data["organization"] is None

    def test_pro_user(self, client, auth_headers, org_with_code):
        code = org_with_code["invite_code"]
        client.post("/api/v1/me/org/join", json={"invite_code": code}, headers=auth_headers)
        resp = client.get("/api/v1/me/org", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "pro"
        assert data["remaining_questions"] is None
        assert data["organization"]["org_name"] == "TestUnion"
