"""
Exam mode routes -- timed exams with anti-cheat measures.
"""
import uuid
import time
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from auth import require_auth
from database import (
    get_questions, get_questions_by_ids,
    create_exam_session, get_exam_session, submit_exam_session,
    increment_tab_switches, get_exam_history,
)
from services.exam_service import (
    shuffle_questions, unshuffle_answers, is_expired, calculate_penalty,
)
from access_control import is_within_daily_limit, get_user_tier
from database_invite import increment_daily_usage

router = APIRouter(tags=["Exam"])


class ExamStartRequest(BaseModel):
    bank_id: Optional[str] = Field(None, description="Question bank ID")
    duration_min: int = Field(60, ge=10, le=180, description="Exam duration in minutes")
    chapter: Optional[str] = Field(None)
    difficulty: Optional[int] = Field(None, ge=1, le=3)
    num_choice: int = Field(20, ge=0, le=80)
    num_multichoice: int = Field(5, ge=0, le=30)
    num_tf: int = Field(10, ge=0, le=50)
    num_scenario: int = Field(0, ge=0, le=10)


class ExamSubmitRequest(BaseModel):
    answers: dict[str, str] = Field(..., description="question_id -> answer")
    tab_switches: int = Field(0, ge=0)


def _fetch_exam_questions(req: ExamStartRequest) -> list[dict]:
    """Fetch questions for exam without session-based exclusion."""
    common = dict(
        chapter=req.chapter, difficulty=req.difficulty,
        bank_id=req.bank_id,
    )
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


def _check_answer(user_answer: str, correct_answer: str, q_type: str) -> bool:
    """Unified answer checking logic."""
    user = user_answer.strip().upper().replace(",", "").replace(" ", "")
    correct = correct_answer.strip().upper()
    if q_type in ("multichoice", "scenario_multichoice"):
        return "".join(sorted(user)) == "".join(sorted(correct))
    return user == correct


@router.post("/exam/start")
async def start_exam(req: ExamStartRequest, user: dict = Depends(require_auth)):
    """Start a timed exam session with shuffled questions."""
    user_id = user.get("sub", "")

    # Free tier daily limit check
    if not is_within_daily_limit(user_id):
        raise HTTPException(403, "Daily question limit reached. Upgrade to Pro for unlimited access.")

    questions = _fetch_exam_questions(req)

    if not questions:
        raise HTTPException(400, "No questions found matching criteria")

    seed = int(time.time() * 1000) % (2**31)
    shuffled, shuffle_map = shuffle_questions(questions, seed)

    question_ids = [q["id"] for q in questions]

    # Track daily usage for free tier
    if get_user_tier(user_id) == "free":
        increment_daily_usage(user_id, count=len(question_ids))

    session = create_exam_session(
        user_id=user_id,
        bank_id=req.bank_id or "ipas-netzero-mid",
        question_ids=question_ids,
        shuffle_map=shuffle_map,
        duration_min=req.duration_min,
    )

    # Strip answers from shuffled questions
    exam_items = []
    for q in shuffled:
        item = {k: v for k, v in q.items() if k not in ("answer", "explanation")}
        if q.get("type") in ("multichoice", "scenario_multichoice"):
            item["hint"] = "MULTI-SELECT"
        exam_items.append(item)

    return {
        "exam_id": session["id"],
        "duration_min": req.duration_min,
        "started_at": session["started_at"],
        "total": len(exam_items),
        "questions": exam_items,
    }


@router.post("/exam/{exam_id}/submit")
async def submit_exam(
    exam_id: str, req: ExamSubmitRequest, user: dict = Depends(require_auth),
):
    """Submit exam answers for grading."""
    user_id = user.get("sub", "")
    session = get_exam_session(exam_id, user_id)

    if not session:
        raise HTTPException(404, "Exam session not found")
    if session["status"] != "active":
        raise HTTPException(400, "Exam already submitted")

    expired = is_expired(session["started_at"], session["duration_min"])

    # Use server-tracked tab_switches (authoritative), not client-provided value
    server_tab_switches = session.get("tab_switches") or 0

    # Unshuffle answers to canonical form
    canonical_answers = unshuffle_answers(req.answers, session.get("shuffle_map") or {})

    # Grade
    int_ids = [int(qid) for qid in canonical_answers if qid.isdigit()]
    questions = get_questions_by_ids(int_ids)
    q_map = {str(q["id"]): q for q in questions}

    correct_count = 0
    results = []
    for qid, user_answer in canonical_answers.items():
        q = q_map.get(qid)
        if not q:
            continue
        is_correct = _check_answer(user_answer, q["answer"], q["type"])
        if is_correct:
            correct_count += 1
        results.append({
            "id": int(qid),
            "is_correct": is_correct,
            "user_answer": user_answer,
            "correct_answer": q["answer"],
            "explanation": q.get("explanation"),
            "content": q.get("content", ""),
            "chapter": q.get("chapter", ""),
            "type": q.get("type", ""),
        })

    total = len(results)
    base_score = correct_count
    final_score = calculate_penalty(server_tab_switches, base_score)

    submit_exam_session(
        exam_id, user_id,
        score=final_score, total=total, tab_switches=server_tab_switches,
        question_results=results,
    )

    # Auto-save to quiz_history + notebook (best-effort)
    try:
        if results:
            from database import save_history_batch
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
        pass

    try:
        wrong_ids = [r["id"] for r in results if not r["is_correct"]]
        if wrong_ids:
            from database_notebook import upsert_wrong_answers
            upsert_wrong_answers(user_id, wrong_ids, "exam")
    except Exception:
        pass

    return {
        "score": final_score,
        "base_score": base_score,
        "total": total,
        "percentage": round(final_score / total * 100, 1) if total else 0,
        "tab_switches": server_tab_switches,
        "penalty": base_score - final_score,
        "expired": expired,
        "results": results,
    }


@router.get("/exam/{exam_id}/results")
async def exam_results(exam_id: str, user: dict = Depends(require_auth)):
    """Get detailed results for a completed exam."""
    user_id = user.get("sub", "")
    session = get_exam_session(exam_id, user_id)
    if not session:
        raise HTTPException(404, "Exam session not found")
    if session["status"] != "submitted":
        raise HTTPException(400, "Exam not yet submitted")

    question_results = session.get("question_results") or []

    return {
        "exam_id": exam_id,
        "score": session.get("score", 0),
        "total": session.get("total", 0),
        "percentage": round(session["score"] / session["total"] * 100, 1) if session.get("total") else 0,
        "tab_switches": session.get("tab_switches", 0),
        "penalty": session.get("base_score", session.get("score", 0)) - session.get("score", 0),
        "duration_min": session.get("duration_min", 0),
        "started_at": session.get("started_at"),
        "question_results": question_results,
    }


@router.post("/exam/{exam_id}/tab-switch")
async def record_tab_switch(exam_id: str, user: dict = Depends(require_auth)):
    """Record a tab switch event."""
    user_id = user.get("sub", "")
    session = get_exam_session(exam_id, user_id)
    if not session:
        raise HTTPException(404, "Exam session not found")
    if session["status"] != "active":
        raise HTTPException(400, "Exam not active")

    new_count = increment_tab_switches(exam_id, user_id)
    return {
        "tab_switches": new_count,
        "warning": "Tab switching has been recorded. Repeated switches may reduce your score.",
    }


@router.get("/exam/history")
async def exam_history_list(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_auth),
):
    """List past exam results."""
    user_id = user.get("sub", "")
    history = get_exam_history(user_id, limit=limit, offset=offset)
    return {"exams": history, "count": len(history)}
