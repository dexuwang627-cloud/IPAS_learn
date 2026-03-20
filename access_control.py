"""
Access control layer -- tier resolution and feature gating.

Users belong to either "free" or "pro" tier:
- free: no active pro subscription, limited daily questions (10/day)
- pro: redeemed invite code with unexpired subscription, unlimited access
"""
import logging
from typing import Optional

from database_invite import get_user_pro, check_daily_limit, get_daily_usage

logger = logging.getLogger(__name__)

FREE_DAILY_LIMIT = 10


def get_user_tier(user_id: str) -> str:
    """Resolve user tier: 'pro' if has active subscription, otherwise 'free'."""
    pro = get_user_pro(user_id)
    if pro:
        return "pro"
    return "free"


def is_within_daily_limit(user_id: str) -> bool:
    """Check if user can still use questions today.
    Pro users are always allowed. Free users have a daily cap.
    """
    tier = get_user_tier(user_id)
    if tier == "pro":
        return True
    return check_daily_limit(user_id, limit=FREE_DAILY_LIMIT)


def get_remaining_questions(user_id: str) -> Optional[int]:
    """Get remaining questions for today. None means unlimited (pro)."""
    tier = get_user_tier(user_id)
    if tier == "pro":
        return None
    used = get_daily_usage(user_id)
    return max(0, FREE_DAILY_LIMIT - used)


def get_tier_limits(tier: str) -> dict:
    """Return feature access map for a tier."""
    if tier == "pro":
        return {
            "daily_questions": None,  # unlimited
            "notebook_view_limit": None,  # unlimited
            "notebook_practice": True,
            "dashboard_full": True,
        }
    return {
        "daily_questions": FREE_DAILY_LIMIT,
        "notebook_view_limit": 5,
        "notebook_practice": False,
        "dashboard_full": False,
    }
