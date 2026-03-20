"""
Quiz history routes -- server-side persistence of answer history.
"""
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from auth import require_auth
from database import save_history_batch, get_history, get_weakness_stats, clear_history

router = APIRouter(tags=["History"])

_VALID_TYPES = frozenset(
    {"choice", "truefalse", "multichoice", "scenario_choice", "scenario_multichoice"}
)


class HistoryEntry(BaseModel):
    question_id: int
    question_type: str
    chapter: Optional[str] = None
    content_preview: Optional[str] = Field(None, max_length=200)
    is_correct: bool
    user_answer: str
    correct_answer: Optional[str] = None


class HistoryBatch(BaseModel):
    results: list[HistoryEntry] = Field(..., max_length=100)


@router.post("/history")
async def save_quiz_history(batch: HistoryBatch, user: dict = Depends(require_auth)):
    """Save a batch of quiz results to history."""
    user_id = user.get("sub", "")
    entries = []
    for entry in batch.results:
        if entry.question_type not in _VALID_TYPES:
            raise HTTPException(400, f"Invalid question_type: {entry.question_type}")
        entries.append({
            "user_id": user_id,
            "question_id": entry.question_id,
            "question_type": entry.question_type,
            "chapter": entry.chapter,
            "content_preview": (entry.content_preview or "")[:200],
            "is_correct": entry.is_correct,
            "user_answer": entry.user_answer,
            "correct_answer": entry.correct_answer,
        })
    count = save_history_batch(user_id, entries)
    return {"saved": count}


@router.get("/history")
async def list_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_auth),
):
    """Get paginated quiz history for the current user."""
    user_id = user.get("sub", "")
    rows = get_history(user_id, limit=limit, offset=offset)
    return {"history": rows, "count": len(rows)}


@router.get("/history/weakness")
async def weakness_stats(user: dict = Depends(require_auth)):
    """Get aggregated weakness stats by chapter."""
    user_id = user.get("sub", "")
    stats = get_weakness_stats(user_id)
    return {"stats": stats}


@router.delete("/history")
async def delete_history(user: dict = Depends(require_auth)):
    """Clear all history for the current user."""
    user_id = user.get("sub", "")
    count = clear_history(user_id)
    return {"cleared": count}
