"""
隨機測驗路由
"""
from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from database import get_questions
from services.exam_builder import build_exam_pdf

router = APIRouter(tags=["隨機測驗"])


class QuizRequest(BaseModel):
    chapter: Optional[str] = Field(None, description="指定章節，None 為全部")
    difficulty: Optional[int] = Field(None, ge=1, le=3, description="難度 1-3")
    num_choice: int = Field(10, ge=0, le=50, description="選擇題數量")
    num_tf: int = Field(5, ge=0, le=30, description="是非題數量")


class AnswerSheet(BaseModel):
    answers: dict[str, str] = Field(
        ..., description="題目 ID → 使用者作答，例如 {'1': 'A', '5': 'T'}"
    )


@router.post("/quiz")
async def start_quiz(req: QuizRequest):
    """依條件隨機出題"""
    choice_qs = get_questions(
        chapter=req.chapter,
        difficulty=req.difficulty,
        q_type="choice",
        limit=req.num_choice,
    ) if req.num_choice > 0 else []

    tf_qs = get_questions(
        chapter=req.chapter,
        difficulty=req.difficulty,
        q_type="truefalse",
        limit=req.num_tf,
    ) if req.num_tf > 0 else []

    questions = choice_qs + tf_qs

    # 隱藏答案
    quiz_items = []
    for q in questions:
        item = {k: v for k, v in q.items() if k != "answer"}
        quiz_items.append(item)

    return {
        "total": len(questions),
        "questions": quiz_items,
        "_answer_key": {str(q["id"]): q["answer"] for q in questions},
    }


@router.post("/quiz/check")
async def check_answers(sheet: AnswerSheet):
    """批改答案"""
    all_ids = list(sheet.answers.keys())
    if not all_ids:
        return {"score": 0, "total": 0, "results": []}

    questions = get_questions()
    q_map = {str(q["id"]): q for q in questions}

    results = []
    correct_count = 0
    for qid, user_answer in sheet.answers.items():
        q = q_map.get(qid)
        if not q:
            continue
        is_correct = user_answer.strip().upper() == q["answer"].strip().upper()
        if is_correct:
            correct_count += 1
        results.append({
            "id": int(qid),
            "content": q["content"],
            "user_answer": user_answer,
            "correct_answer": q["answer"],
            "is_correct": is_correct,
        })

    total = len(results)
    return {
        "score": correct_count,
        "total": total,
        "percentage": round(correct_count / total * 100, 1) if total else 0,
        "results": results,
    }


@router.post("/quiz/pdf")
async def quiz_pdf(
    chapter: Optional[str] = Query(None),
    difficulty: Optional[int] = Query(None, ge=1, le=3),
    num_choice: int = Query(10, ge=0, le=50),
    num_tf: int = Query(5, ge=0, le=30),
    include_answers: bool = Query(False),
):
    """產生 PDF 試卷"""
    choice_qs = get_questions(chapter=chapter, difficulty=difficulty,
                              q_type="choice", limit=num_choice)
    tf_qs = get_questions(chapter=chapter, difficulty=difficulty,
                          q_type="truefalse", limit=num_tf)
    questions = choice_qs + tf_qs

    if not questions:
        return {"error": "題庫中沒有符合條件的題目"}

    pdf_bytes = build_exam_pdf(questions, include_answers=include_answers)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=ipas_quiz.pdf"}
    )
