"""
題庫管理路由
"""
from fastapi import APIRouter, Query
from typing import Optional
from database import get_questions, get_chapters, get_stats, delete_question

router = APIRouter(tags=["題庫管理"])


@router.get("/chapters")
async def list_chapters():
    """取得所有章節列表"""
    return {"chapters": get_chapters()}


@router.get("/stats")
async def stats():
    """取得題庫統計"""
    return get_stats()


@router.get("/questions")
async def list_questions(
    chapter: Optional[str] = Query(None, description="篩選章節"),
    difficulty: Optional[int] = Query(None, ge=1, le=3, description="篩選難度 1-3"),
    q_type: Optional[str] = Query(None, description="篩選題型: choice / truefalse"),
    limit: Optional[int] = Query(None, ge=1, le=200, description="最多回傳題數"),
):
    """查詢題庫中的題目"""
    return {
        "questions": get_questions(
            chapter=chapter,
            difficulty=difficulty,
            q_type=q_type,
            limit=limit,
        )
    }


@router.delete("/questions/{question_id}")
async def remove_question(question_id: int):
    """刪除指定題目"""
    delete_question(question_id)
    return {"ok": True}
