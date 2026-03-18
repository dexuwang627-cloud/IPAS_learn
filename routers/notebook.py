"""Wrong answer notebook API routes."""
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional

from auth import require_auth
from database import get_questions_by_ids
from access_control import get_user_tier, get_tier_limits
from database_notebook import (
    get_notebook_entries,
    get_notebook_stats,
    get_notebook_question_ids,
    toggle_bookmark,
    remove_notebook_entry,
)

router = APIRouter(prefix="/notebook", tags=["notebook"])


class NotebookPracticeRequest(BaseModel):
    num_questions: int = 15
    filter: str = "all"
    chapter: Optional[str] = None


@router.get("")
async def list_notebook(
    user: dict = Depends(require_auth),
    filter: str = Query("all", pattern="^(all|bookmarked|quiz|exam)$"),
    chapter: Optional[str] = None,
    sort: str = Query("recent", pattern="^(recent|frequency)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List wrong/bookmarked questions with pagination."""
    tier = get_user_tier(user["sub"])
    limits = get_tier_limits(tier)
    # Free tier: cap visible entries
    effective_limit = limit
    if limits["notebook_view_limit"] is not None:
        effective_limit = min(limit, limits["notebook_view_limit"])

    items, total = get_notebook_entries(
        user["sub"], filter, chapter, sort, effective_limit, offset,
    )
    return {"items": items, "total": total, "limit": effective_limit, "offset": offset, "tier": tier}


@router.get("/stats")
async def notebook_stats(user: dict = Depends(require_auth)):
    """Get notebook summary stats."""
    return get_notebook_stats(user["sub"])


@router.post("/{question_id}/bookmark")
async def bookmark_question(
    question_id: int, user: dict = Depends(require_auth),
):
    """Toggle bookmark on a question."""
    questions = get_questions_by_ids([question_id])
    if not questions:
        raise HTTPException(404, "Question not found")
    return toggle_bookmark(user["sub"], question_id)


@router.delete("/{question_id}")
async def delete_notebook_entry_route(
    question_id: int, user: dict = Depends(require_auth),
):
    """Remove a question from notebook."""
    deleted = remove_notebook_entry(user["sub"], question_id)
    if not deleted:
        raise HTTPException(404, "Entry not found")
    return {"deleted": True}


@router.post("/practice")
async def notebook_practice(
    req: NotebookPracticeRequest, user: dict = Depends(require_auth),
):
    """Generate a quiz from wrong/bookmarked questions. Pro only."""
    tier = get_user_tier(user["sub"])
    if not get_tier_limits(tier)["notebook_practice"]:
        raise HTTPException(403, "Notebook practice requires Pro tier")
    question_ids = get_notebook_question_ids(
        user["sub"], req.filter, req.chapter, req.num_questions,
    )
    if not question_ids:
        raise HTTPException(400, "No questions in notebook")

    questions = get_questions_by_ids(question_ids)
    stripped = [
        {k: v for k, v in q.items() if k not in ("answer", "explanation")}
        for q in questions
    ]

    return {
        "questions": stripped,
        "total": len(stripped),
        "source": "notebook",
    }
