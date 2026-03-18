"""
Tests for database_org.py -- organization, members, daily usage.
"""
import time
from datetime import date

import pytest

from tests.conftest import _make_token


@pytest.fixture
def org_db():
    """Ensure org tables are migrated."""
    import database_org
    database_org.migrate_add_org_tables()
    return database_org


class TestCreateOrg:
    def test_create_org_returns_dict(self, org_db):
        org = org_db.create_org("Test Union", seat_limit=10, created_by="admin-1")
        assert org["name"] == "Test Union"
        assert org["seat_limit"] == 10
        assert org["is_active"] is True
        assert len(org["invite_code"]) == 8
        assert org["invite_code"].isalnum()

    def test_create_org_unique_invite_codes(self, org_db):
        org1 = org_db.create_org("Org1", seat_limit=5, created_by="admin-1")
        org2 = org_db.create_org("Org2", seat_limit=5, created_by="admin-1")
        assert org1["invite_code"] != org2["invite_code"]


class TestGetOrg:
    def test_get_org_by_id(self, org_db):
        org = org_db.create_org("Findme", seat_limit=3, created_by="admin-1")
        found = org_db.get_org(org["id"])
        assert found["name"] == "Findme"
        assert found["seat_limit"] == 3

    def test_get_org_not_found(self, org_db):
        assert org_db.get_org(99999) is None

    def test_get_org_by_invite_code(self, org_db):
        org = org_db.create_org("CodeOrg", seat_limit=5, created_by="admin-1")
        found = org_db.get_org_by_invite_code(org["invite_code"])
        assert found["id"] == org["id"]

    def test_get_org_by_invite_code_not_found(self, org_db):
        assert org_db.get_org_by_invite_code("ZZZZZZZZ") is None


class TestUpdateOrg:
    def test_update_org_name(self, org_db):
        org = org_db.create_org("Old", seat_limit=5, created_by="admin-1")
        updated = org_db.update_org(org["id"], name="New")
        assert updated["name"] == "New"
        assert updated["seat_limit"] == 5

    def test_update_org_seat_limit(self, org_db):
        org = org_db.create_org("Seats", seat_limit=5, created_by="admin-1")
        updated = org_db.update_org(org["id"], seat_limit=20)
        assert updated["seat_limit"] == 20

    def test_update_org_deactivate(self, org_db):
        org = org_db.create_org("Active", seat_limit=5, created_by="admin-1")
        updated = org_db.update_org(org["id"], is_active=False)
        assert updated["is_active"] is False

    def test_update_nonexistent_org(self, org_db):
        assert org_db.update_org(99999, name="Nope") is None


class TestListOrgs:
    def test_list_orgs_empty(self, org_db):
        orgs = org_db.list_orgs()
        assert orgs == []

    def test_list_orgs_returns_all(self, org_db):
        org_db.create_org("A", seat_limit=5, created_by="admin-1")
        org_db.create_org("B", seat_limit=10, created_by="admin-1")
        orgs = org_db.list_orgs()
        assert len(orgs) == 2


class TestMembers:
    def test_add_member(self, org_db):
        org = org_db.create_org("MemberOrg", seat_limit=5, created_by="admin-1")
        result = org_db.add_member(org["id"], "user-1")
        assert result["org_id"] == org["id"]
        assert result["user_id"] == "user-1"

    def test_add_member_seat_full(self, org_db):
        org = org_db.create_org("Full", seat_limit=1, created_by="admin-1")
        org_db.add_member(org["id"], "user-1")
        with pytest.raises(ValueError, match="[Ss]eat"):
            org_db.add_member(org["id"], "user-2")

    def test_add_member_duplicate(self, org_db):
        org = org_db.create_org("Dup", seat_limit=5, created_by="admin-1")
        org_db.add_member(org["id"], "user-1")
        with pytest.raises(ValueError, match="[Aa]lready"):
            org_db.add_member(org["id"], "user-1")

    def test_remove_member(self, org_db):
        org = org_db.create_org("RemOrg", seat_limit=5, created_by="admin-1")
        org_db.add_member(org["id"], "user-1")
        assert org_db.remove_member(org["id"], "user-1") is True
        assert org_db.remove_member(org["id"], "user-1") is False

    def test_list_members(self, org_db):
        org = org_db.create_org("ListOrg", seat_limit=5, created_by="admin-1")
        org_db.add_member(org["id"], "user-1")
        org_db.add_member(org["id"], "user-2")
        members = org_db.list_members(org["id"])
        assert len(members) == 2
        user_ids = {m["user_id"] for m in members}
        assert user_ids == {"user-1", "user-2"}

    def test_count_seats(self, org_db):
        org = org_db.create_org("CountOrg", seat_limit=5, created_by="admin-1")
        assert org_db.count_seats(org["id"]) == 0
        org_db.add_member(org["id"], "user-1")
        assert org_db.count_seats(org["id"]) == 1

    def test_get_user_org(self, org_db):
        org = org_db.create_org("UserOrg", seat_limit=5, created_by="admin-1")
        org_db.add_member(org["id"], "user-1")
        result = org_db.get_user_org("user-1")
        assert result["org_id"] == org["id"]
        assert result["org_name"] == "UserOrg"

    def test_get_user_org_none(self, org_db):
        assert org_db.get_user_org("nobody") is None

    def test_add_member_inactive_org(self, org_db):
        org = org_db.create_org("Inactive", seat_limit=5, created_by="admin-1")
        org_db.update_org(org["id"], is_active=False)
        with pytest.raises(ValueError, match="[Ii]nactive|[Nn]ot active"):
            org_db.add_member(org["id"], "user-1")


class TestDailyUsage:
    def test_increment_and_get(self, org_db):
        org_db.increment_daily_usage("user-1", count=3)
        usage = org_db.get_daily_usage("user-1")
        assert usage == 3

    def test_increment_accumulates(self, org_db):
        org_db.increment_daily_usage("user-1", count=2)
        org_db.increment_daily_usage("user-1", count=3)
        assert org_db.get_daily_usage("user-1") == 5

    def test_check_daily_limit_under(self, org_db):
        org_db.increment_daily_usage("user-1", count=3)
        assert org_db.check_daily_limit("user-1", limit=5) is True

    def test_check_daily_limit_at(self, org_db):
        org_db.increment_daily_usage("user-1", count=5)
        assert org_db.check_daily_limit("user-1", limit=5) is False

    def test_check_daily_limit_over(self, org_db):
        org_db.increment_daily_usage("user-1", count=6)
        assert org_db.check_daily_limit("user-1", limit=5) is False

    def test_get_daily_usage_zero(self, org_db):
        assert org_db.get_daily_usage("new-user") == 0
