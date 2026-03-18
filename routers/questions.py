"""
題庫管理路由
"""
from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Optional
from database import get_questions, get_chapters, get_stats, delete_question
from auth import require_auth, optional_auth, is_admin

router = APIRouter(tags=["題庫管理"])

# Fields to strip from non-admin responses
_SENSITIVE_FIELDS = {"answer", "explanation"}


def _strip_answers(questions: list[dict]) -> list[dict]:
    """Return new list of question dicts without answer/explanation fields."""
    return [
        {k: v for k, v in q.items() if k not in _SENSITIVE_FIELDS}
        for q in questions
    ]


@router.get("/chapters")
async def list_chapters(bank_id: Optional[str] = Query(None)):
    """取得所有章節列表"""
    return {"chapters": get_chapters(bank_id=bank_id)}


@router.get("/stats")
async def stats(bank_id: Optional[str] = Query(None)):
    """取得題庫統計"""
    return get_stats(bank_id=bank_id)


@router.get("/questions")
async def list_questions(
    chapter: Optional[str] = Query(None, description="篩選章節"),
    difficulty: Optional[int] = Query(None, ge=1, le=3, description="篩選難度 1-3"),
    q_type: Optional[str] = Query(None, description="篩選題型: choice / truefalse"),
    limit: Optional[int] = Query(None, ge=1, le=200, description="最多回傳題數"),
    bank_id: Optional[str] = Query(None, description="題庫 ID"),
    user: Optional[dict] = Depends(optional_auth),
):
    """查詢題庫中的題目 -- non-admin users will not see answer/explanation"""
    questions = get_questions(
        chapter=chapter,
        difficulty=difficulty,
        q_type=q_type,
        limit=limit,
        bank_id=bank_id,
    )
    if not user or not is_admin(user):
        questions = _strip_answers(questions)
    return {"questions": questions}


@router.delete("/questions/{question_id}")
async def remove_question(question_id: int, user: dict = Depends(require_auth)):
    """刪除指定題目 (admin only)"""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    delete_question(question_id)
    return {"ok": True}
