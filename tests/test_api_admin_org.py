"""
API tests for admin org endpoints.
"""
import pytest
from tests.conftest import _make_token


@pytest.fixture
def org_db():
    import database_org
    database_org.migrate_add_org_tables()
    return database_org


class TestAdminCreateOrg:
    def test_create_org_admin(self, client, admin_headers, org_db):
        resp = client.post("/api/v1/org", json={"name": "TestOrg", "seat_limit": 10}, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "TestOrg"
        assert data["seat_limit"] == 10
        assert len(data["invite_code"]) == 8

    def test_create_org_non_admin_forbidden(self, client, auth_headers, org_db):
        resp = client.post("/api/v1/org", json={"name": "NoAccess", "seat_limit": 5}, headers=auth_headers)
        assert resp.status_code == 403

    def test_create_org_no_auth(self, client, org_db):
        resp = client.post("/api/v1/org", json={"name": "NoAuth", "seat_limit": 5})
        assert resp.status_code == 422 or resp.status_code == 401

    def test_create_org_invalid_seat(self, client, admin_headers, org_db):
        resp = client.post("/api/v1/org", json={"name": "Bad", "seat_limit": 0}, headers=admin_headers)
        assert resp.status_code == 422


class TestAdminGetOrg:
    def test_get_org(self, client, admin_headers, org_db):
        create = client.post("/api/v1/org", json={"name": "Get", "seat_limit": 5}, headers=admin_headers)
        org_id = create.json()["id"]
        resp = client.get(f"/api/v1/org/{org_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Get"

    def test_get_org_not_found(self, client, admin_headers, org_db):
        resp = client.get("/api/v1/org/99999", headers=admin_headers)
        assert resp.status_code == 404


class TestAdminUpdateOrg:
    def test_update_org_name(self, client, admin_headers, org_db):
        create = client.post("/api/v1/org", json={"name": "Old", "seat_limit": 5}, headers=admin_headers)
        org_id = create.json()["id"]
        resp = client.patch(f"/api/v1/org/{org_id}", json={"name": "New"}, headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"

    def test_update_org_not_found(self, client, admin_headers, org_db):
        resp = client.patch("/api/v1/org/99999", json={"name": "X"}, headers=admin_headers)
        assert resp.status_code == 404


class TestAdminDeactivateOrg:
    def test_deactivate(self, client, admin_headers, org_db):
        create = client.post("/api/v1/org", json={"name": "Die", "seat_limit": 5}, headers=admin_headers)
        org_id = create.json()["id"]
        resp = client.delete(f"/api/v1/org/{org_id}", headers=admin_headers)
        assert resp.status_code == 200
        # Verify deactivated
        get = client.get(f"/api/v1/org/{org_id}", headers=admin_headers)
        assert get.json()["is_active"] is False


class TestAdminListOrgs:
    def test_list_orgs(self, client, admin_headers, org_db):
        client.post("/api/v1/org", json={"name": "A", "seat_limit": 5}, headers=admin_headers)
        client.post("/api/v1/org", json={"name": "B", "seat_limit": 10}, headers=admin_headers)
        resp = client.get("/api/v1/org", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestAdminMembers:
    def test_list_members(self, client, admin_headers, org_db):
        create = client.post("/api/v1/org", json={"name": "Members", "seat_limit": 5}, headers=admin_headers)
        org_id = create.json()["id"]
        org_db.add_member(org_id, "user-x")
        resp = client.get(f"/api/v1/org/{org_id}/members", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["used_seats"] == 1
        assert len(data["members"]) == 1

    def test_remove_member(self, client, admin_headers, org_db):
        create = client.post("/api/v1/org", json={"name": "Rem", "seat_limit": 5}, headers=admin_headers)
        org_id = create.json()["id"]
        org_db.add_member(org_id, "user-rm")
        resp = client.delete(f"/api/v1/org/{org_id}/members/user-rm", headers=admin_headers)
        assert resp.status_code == 200
        # Verify removed
        members = client.get(f"/api/v1/org/{org_id}/members", headers=admin_headers)
        assert members.json()["used_seats"] == 0

    def test_remove_nonexistent_member(self, client, admin_headers, org_db):
        create = client.post("/api/v1/org", json={"name": "NoMem", "seat_limit": 5}, headers=admin_headers)
        org_id = create.json()["id"]
        resp = client.delete(f"/api/v1/org/{org_id}/members/nobody", headers=admin_headers)
        assert resp.status_code == 404
