"""
題目生成路由 — 觸發 Ollama 自動出題
"""
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional
from services.question_generator import generate_from_text_files, generate_questions
from database import insert_question, get_stats
from pathlib import Path
import json

router = APIRouter(tags=["題目生成"])

# 生成狀態追蹤
_generation_status = {"running": False, "last_result": None}


class GenerateRequest(BaseModel):
    num_choice: int = Field(3, ge=1, le=10, description="每份教材產生的選擇題數")
    num_tf: int = Field(2, ge=1, le=5, description="每份教材產生的是非題數")


def _run_generation(num_choice: int, num_tf: int):
    """背景執行產題任務"""
    _generation_status["running"] = True
    _generation_status["last_result"] = None
    try:
        questions = generate_from_text_files(
            num_choice=num_choice, num_tf=num_tf
        )
        inserted = 0
        for q in questions:
            try:
                insert_question(q)
                inserted += 1
            except Exception as e:
                print(f"  ⚠️ 插入失敗: {e}")
        _generation_status["last_result"] = {
            "generated": len(questions),
            "inserted": inserted,
            "stats": get_stats(),
        }
    except Exception as e:
        _generation_status["last_result"] = {"error": str(e)}
    finally:
        _generation_status["running"] = False


@router.post("/generate")
async def trigger_generation(req: GenerateRequest, bg: BackgroundTasks):
    """觸發自動產題（背景執行）"""
    if _generation_status["running"]:
        return {"status": "already_running", "message": "產題任務正在執行中，請稍候"}

    bg.add_task(_run_generation, req.num_choice, req.num_tf)
    return {"status": "started", "message": "已開始產題，請透過 /api/generate/status 查看進度"}


@router.get("/generate/status")
async def generation_status():
    """查看產題任務狀態"""
    return {
        "running": _generation_status["running"],
        "result": _generation_status["last_result"],
    }


class SingleGenerateRequest(BaseModel):
    text: str = Field(..., min_length=50, description="教材文本")
    chapter: str = Field(..., description="章節名稱")
    num_choice: int = Field(3, ge=1, le=10)
    num_tf: int = Field(2, ge=1, le=5)
    difficulty: Optional[int] = Field(None, ge=1, le=3)
    auto_save: bool = Field(True, description="是否自動存入題庫")


@router.post("/generate/single")
async def generate_single(req: SingleGenerateRequest):
    """從指定文本產生題目"""
    questions = generate_questions(
        text=req.text,
        chapter=req.chapter,
        source_file="manual_input",
        num_choice=req.num_choice,
        num_tf=req.num_tf,
        difficulty=req.difficulty,
    )

    if req.auto_save:
        for q in questions:
            insert_question(q)

    return {"generated": len(questions), "questions": questions}
