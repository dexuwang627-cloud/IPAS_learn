"""Learning dashboard API routes."""
from fastapi import APIRouter, Depends, Query, HTTPException

from auth import require_auth
from access_control import get_user_tier, get_tier_limits
from database_dashboard import (
    get_accuracy_trend,
    get_daily_volume,
    get_chapter_accuracy,
    get_dashboard_summary,
    get_chapter_progress,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _require_dashboard_full(user: dict = Depends(require_auth)) -> dict:
    """Dependency: require Pro tier for full dashboard access."""
    tier = get_user_tier(user["sub"])
    if not get_tier_limits(tier)["dashboard_full"]:
        raise HTTPException(403, "Full dashboard requires Pro tier")
    return user


@router.get("/accuracy-trend")
async def accuracy_trend(
    user: dict = Depends(_require_dashboard_full),
    granularity: str = Query("day", pattern="^(day|week)$"),
    days: int = Query(30, ge=1, le=365),
):
    """Get accuracy trend over time. Pro only."""
    data = get_accuracy_trend(user["sub"], granularity, days)
    return {"granularity": granularity, "data": data}


@router.get("/volume")
async def volume(
    user: dict = Depends(_require_dashboard_full),
    days: int = Query(30, ge=1, le=365),
):
    """Get daily practice volume. Pro only."""
    return {"data": get_daily_volume(user["sub"], days)}


@router.get("/chapter-accuracy")
async def chapter_accuracy(user: dict = Depends(_require_dashboard_full)):
    """Get per-chapter accuracy breakdown. Pro only."""
    return {"data": get_chapter_accuracy(user["sub"])}


@router.get("/summary")
async def summary(user: dict = Depends(require_auth)):
    """Get combined dashboard summary stats."""
    return get_dashboard_summary(user["sub"])


@router.get("/chapter-progress")
async def chapter_progress(user: dict = Depends(require_auth)):
    """Get per-chapter progress: total questions in bank vs user attempted/correct."""
    return {"data": get_chapter_progress(user["sub"])}
