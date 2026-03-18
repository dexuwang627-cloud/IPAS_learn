"""
Tests for access_control.py -- tier resolution and daily limits.
"""
import pytest


@pytest.fixture
def org_db():
    import database_org
    database_org.migrate_add_org_tables()
    return database_org


@pytest.fixture
def ac():
    import access_control
    return access_control


class TestGetUserTier:
    def test_free_user_no_org(self, ac):
        assert ac.get_user_tier("no-org-user") == "free"

    def test_pro_user_in_active_org(self, ac, org_db):
        org = org_db.create_org("ProOrg", seat_limit=5, created_by="admin")
        org_db.add_member(org["id"], "pro-user-1")
        assert ac.get_user_tier("pro-user-1") == "pro"

    def test_free_user_in_inactive_org(self, ac, org_db):
        org = org_db.create_org("DeadOrg", seat_limit=5, created_by="admin")
        org_db.add_member(org["id"], "user-inactive")
        org_db.update_org(org["id"], is_active=False)
        assert ac.get_user_tier("user-inactive") == "free"


class TestDailyLimitCheck:
    def test_under_limit(self, ac, org_db):
        assert ac.is_within_daily_limit("new-user") is True

    def test_at_limit(self, ac, org_db):
        org_db.increment_daily_usage("limit-user", count=5)
        assert ac.is_within_daily_limit("limit-user") is False

    def test_pro_user_unlimited(self, ac, org_db):
        org = org_db.create_org("UnlOrg", seat_limit=5, created_by="admin")
        org_db.add_member(org["id"], "pro-unlimited")
        org_db.increment_daily_usage("pro-unlimited", count=100)
        assert ac.is_within_daily_limit("pro-unlimited") is True


class TestTierLimits:
    def test_free_limits(self, ac):
        limits = ac.get_tier_limits("free")
        assert limits["daily_questions"] == 5
        assert limits["notebook_view_limit"] == 5
        assert limits["notebook_practice"] is False
        assert limits["dashboard_full"] is False

    def test_pro_limits(self, ac):
        limits = ac.get_tier_limits("pro")
        assert limits["daily_questions"] is None  # unlimited
        assert limits["notebook_practice"] is True
        assert limits["dashboard_full"] is True
