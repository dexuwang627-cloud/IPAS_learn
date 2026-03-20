"""
Tests for access_control.py -- tier resolution and daily limits.
"""
import pytest


@pytest.fixture
def invite_db():
    import database_invite
    database_invite.migrate_add_invite_tables()
    return database_invite


@pytest.fixture
def ac():
    import access_control
    return access_control


def _make_pro_user(invite_db, user_id):
    """Create an invite and redeem it for the given user."""
    inv = invite_db.create_invite(duration_days=30, max_uses=10, created_by="admin")
    invite_db.redeem_invite(inv["code"], user_id)


class TestGetUserTier:
    def test_free_user_no_pro(self, ac):
        assert ac.get_user_tier("no-pro-user") == "free"

    def test_pro_user_with_invite(self, ac, invite_db):
        _make_pro_user(invite_db, "pro-user-1")
        assert ac.get_user_tier("pro-user-1") == "pro"


class TestDailyLimitCheck:
    def test_under_limit(self, ac):
        assert ac.is_within_daily_limit("new-user") is True

    def test_at_limit(self, ac, invite_db):
        invite_db.increment_daily_usage("limit-user", count=10)
        assert ac.is_within_daily_limit("limit-user") is False

    def test_pro_user_unlimited(self, ac, invite_db):
        _make_pro_user(invite_db, "pro-unlimited")
        invite_db.increment_daily_usage("pro-unlimited", count=100)
        assert ac.is_within_daily_limit("pro-unlimited") is True


class TestTierLimits:
    def test_free_limits(self, ac):
        limits = ac.get_tier_limits("free")
        assert limits["daily_questions"] == 10
        assert limits["notebook_view_limit"] == 5
        assert limits["notebook_practice"] is False
        assert limits["dashboard_full"] is False

    def test_pro_limits(self, ac):
        limits = ac.get_tier_limits("pro")
        assert limits["daily_questions"] is None  # unlimited
        assert limits["notebook_practice"] is True
        assert limits["dashboard_full"] is True
