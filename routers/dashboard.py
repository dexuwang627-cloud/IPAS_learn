"""Learning dashboard API routes."""
from fastapi import APIRouter, Depends, Query

from auth import require_auth
from database_dashboard import (
    get_accuracy_trend,
    get_daily_volume,
    get_chapter_accuracy,
    get_dashboard_summary,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/accuracy-trend")
async def accuracy_trend(
    user: dict = Depends(require_auth),
    granularity: str = Query("day", pattern="^(day|week)$"),
    days: int = Query(30, ge=1, le=365),
):
    """Get accuracy trend over time."""
    data = get_accuracy_trend(user["sub"], granularity, days)
    return {"granularity": granularity, "data": data}


@router.get("/volume")
async def volume(
    user: dict = Depends(require_auth),
    days: int = Query(30, ge=1, le=365),
):
    """Get daily practice volume."""
    return {"data": get_daily_volume(user["sub"], days)}


@router.get("/chapter-accuracy")
async def chapter_accuracy(user: dict = Depends(require_auth)):
    """Get per-chapter accuracy breakdown."""
    return {"data": get_chapter_accuracy(user["sub"])}


@router.get("/summary")
async def summary(user: dict = Depends(require_auth)):
    """Get combined dashboard summary stats."""
    return get_dashboard_summary(user["sub"])
