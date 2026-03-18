"""
隨機測驗路由 -- 支援單選、複選、情境題 + Supabase session 持久化
"""
import uuid
from fastapi import APIRouter, Query, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from database import get_questions, get_questions_by_ids, get_seen_ids, mark_seen, reset_session, save_history_batch
from auth import require_auth

try:
    from services.exam_builder import build_exam_pdf
except ImportError:
    build_exam_pdf = None

try:
    from services.embedding_service import find_similar
except ImportError:
    find_similar = None

router = APIRouter(tags=["隨機測驗"])


class QuizRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="學習 session ID，用於避免重複出題")
    chapter: Optional[str] = Field(None, description="指定章節，None 為全部")
    difficulty: Optional[int] = Field(None, ge=1, le=3, description="難度 1-3")
    num_choice: int = Field(10, ge=0, le=50, description="單選題數量")
    num_multichoice: int = Field(0, ge=0, le=20, description="複選題數量")
    num_tf: int = Field(5, ge=0, le=30, description="是非題數量")
    num_scenario: int = Field(0, ge=0, le=10, description="情境題組數量")
    bank_id: Optional[str] = Field(None, description="題庫 ID")


class AnswerSheet(BaseModel):
    session_id: Optional[str] = Field(None, description="學習 session ID")
    answers: dict[str, str] = Field(
        ..., description="題目 ID -> 使用者作答，例如 {'1': 'A', '5': 'T', '10': 'AC'}"
    )


def _check_answer(user_answer: str, correct_answer: str, q_type: str) -> bool:
    """統一批改邏輯，支援單選和複選"""
    user = user_answer.strip().upper().replace(",", "").replace(" ", "")
    correct = correct_answer.strip().upper()

    if q_type in ("multichoice", "scenario_multichoice"):
        return "".join(sorted(user)) == "".join(sorted(correct))
    else:
        return user == correct


def _fetch_questions_by_types(req: QuizRequest, exclude: list[int] | None):
    """依題型分別抽取題目"""
    common = dict(chapter=req.chapter, difficulty=req.difficulty, exclude_ids=exclude, bank_id=req.bank_id)

    questions = []

    if req.num_choice > 0:
        questions.extend(get_questions(q_type="choice", limit=req.num_choice, **common))

    if req.num_multichoice > 0:
        questions.extend(get_questions(q_type="multichoice", limit=req.num_multichoice, **common))

    if req.num_tf > 0:
        questions.extend(get_questions(q_type="truefalse", limit=req.num_tf, **common))

    if req.num_scenario > 0:
        scenario_qs = get_questions(q_type="scenario_choice", limit=req.num_scenario * 3, **common)
        scenario_qs += get_questions(q_type="scenario_multichoice", limit=req.num_scenario * 2, **common)

        groups: dict[str, list] = {}
        for q in scenario_qs:
            sid = q.get("scenario_id") or f"standalone_{q['id']}"
            groups.setdefault(sid, []).append(q)

        taken = 0
        for sid, group in groups.items():
            if taken >= req.num_scenario:
                break
            questions.extend(group)
            taken += 1

    return questions


@router.post("/quiz")
async def start_quiz(req: QuizRequest, user: dict = Depends(require_auth)):
    """依條件隨機出題，支援單選、複選、情境題"""
    user_id = user.get("sub", "")
    session_id = req.session_id or str(uuid.uuid4())

    seen = get_seen_ids(user_id, session_id)
    exclude = list(seen) if seen else None

    questions = _fetch_questions_by_types(req, exclude)

    new_ids = [q["id"] for q in questions]
    if new_ids:
        mark_seen(user_id, session_id, new_ids)

    quiz_items = []
    for q in questions:
        item = {k: v for k, v in q.items() if k != "answer"}
        if q["type"] in ("multichoice", "scenario_multichoice"):
            item["hint"] = "本題為複選題，請選擇所有正確選項"
        quiz_items.append(item)

    return {
        "total": len(questions),
        "session_id": session_id,
        "seen_count": len(seen) + len(new_ids),
        "questions": quiz_items,
    }


@router.post("/quiz/check")
async def check_answers(sheet: AnswerSheet, user: dict = Depends(require_auth)):
    """批改答案，支援複選題，答錯附類題推薦"""
    all_ids = list(sheet.answers.keys())
    if not all_ids:
        return {"score": 0, "total": 0, "results": []}

    # Only fetch the questions we need
    int_ids = [int(qid) for qid in all_ids if qid.isdigit()]
    questions = get_questions_by_ids(int_ids)
    q_map = {str(q["id"]): q for q in questions}

    user_id = user.get("sub", "")
    seen = get_seen_ids(user_id, sheet.session_id or "") if sheet.session_id else set()

    results = []
    correct_count = 0
    for qid, user_answer in sheet.answers.items():
        q = q_map.get(qid)
        if not q:
            continue

        is_correct = _check_answer(user_answer, q["answer"], q["type"])
        if is_correct:
            correct_count += 1

        item = {
            "id": int(qid),
            "type": q["type"],
            "content": q["content"],
            "user_answer": user_answer,
            "correct_answer": q["answer"],
            "is_correct": is_correct,
            "explanation": q.get("explanation"),
        }

        if q["type"] in ("multichoice", "scenario_multichoice") and not is_correct:
            user_set = set(user_answer.strip().upper().replace(",", ""))
            correct_set = set(q["answer"])
            item["partial_correct"] = len(user_set & correct_set)
            item["total_correct"] = len(correct_set)

        if not is_correct and find_similar:
            try:
                similar = find_similar(q["content"], threshold=0.75, n_results=3)
                similar = [
                    s for s in similar
                    if s["id"] != int(qid) and s["id"] not in seen
                ][:2]
                item["similar_questions"] = similar
            except Exception:
                item["similar_questions"] = []

        results.append(item)

    total = len(results)

    # Auto-save history (best-effort, never break grading)
    try:
        user_id = user.get("sub", "")
        if user_id and results:
            entries = [
                {
                    "user_id": user_id,
                    "question_id": r["id"],
                    "question_type": r["type"],
                    "chapter": q_map.get(str(r["id"]), {}).get("chapter_group"),
                    "content_preview": r["content"][:200] if r.get("content") else None,
                    "is_correct": r["is_correct"],
                    "user_answer": r["user_answer"],
                    "correct_answer": r["correct_answer"],
                }
                for r in results
            ]
            save_history_batch(user_id, entries)
    except Exception:
        pass  # history save failure must not break grading

    return {
        "score": correct_count,
        "total": total,
        "percentage": round(correct_count / total * 100, 1) if total else 0,
        "results": results,
    }


@router.post("/quiz/reset")
async def reset_quiz_session(
    session_id: str = Query(..., description="要重置的 session ID"),
    user: dict = Depends(require_auth),
):
    """重置 session"""
    user_id = user.get("sub", "")
    cleared = reset_session(user_id, session_id)
    return {"session_id": session_id, "cleared": cleared}


@router.post("/quiz/pdf")
async def quiz_pdf(
    chapter: Optional[str] = Query(None),
    difficulty: Optional[int] = Query(None, ge=1, le=3),
    num_choice: int = Query(10, ge=0, le=50),
    num_tf: int = Query(5, ge=0, le=30),
    include_answers: bool = Query(False),
    include_explanations: bool = Query(False),
    user: dict = Depends(require_auth),
):
    """產生 PDF 試卷"""
    choice_qs = get_questions(chapter=chapter, difficulty=difficulty,
                              q_type="choice", limit=num_choice)
    tf_qs = get_questions(chapter=chapter, difficulty=difficulty,
                          q_type="truefalse", limit=num_tf)
    questions = choice_qs + tf_qs

    if not questions:
        return {"error": "題庫中沒有符合條件的題目"}

    if not build_exam_pdf:
        return {"error": "PDF export not available in this deployment"}

    pdf_bytes = build_exam_pdf(questions, include_answers=include_answers,
                               include_explanations=include_explanations)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=ipas_quiz.pdf"}
    )
