"""
Question Generator Service
使用 Ollama 本地 LLM 從文本自動產生 iPAS 考試題目
"""
import json
import re
import ollama
from pathlib import Path
from typing import Optional

from database import insert_question as _db_insert
from services.embedding_service import add_question as _embed_add, find_similar as _embed_find

MODEL = "gemma3:4b"

SYSTEM_PROMPT = """你是一位 iPAS 產業人才能力鑑定的出題專家。
你的任務是根據給定的學習教材內容，產生高品質的考試題目。

請嚴格遵守以下 JSON 格式輸出，不要輸出任何其他文字：

```json
[
  {
    "type": "choice",
    "content": "題目內容",
    "option_a": "選項A",
    "option_b": "選項B",
    "option_c": "選項C",
    "option_d": "選項D",
    "answer": "A",
    "difficulty": 1
  },
  {
    "type": "truefalse",
    "content": "題目內容",
    "answer": "T",
    "difficulty": 2
  }
]
```

規則：
1. 選擇題 answer 只能是 A/B/C/D
2. 是非題 answer 只能是 T/F
3. difficulty 只能是 1(簡單)、2(中等)、3(困難)
4. 簡單題：定義、基本概念
5. 中等題：比較、應用、流程
6. 困難題：計算、整合分析、情境判斷
7. 題目必須基於給定教材內容，不可憑空捏造
8. 每題必須有明確唯一正確答案
"""


def _build_prompt(text: str, num_choice: int = 3, num_tf: int = 2,
                  difficulty: Optional[int] = None) -> str:
    diff_hint = ""
    if difficulty:
        labels = {1: "簡單（定義、基本概念）", 2: "中等（比較、應用）", 3: "困難（計算、整合分析）"}
        diff_hint = f"\n請只產生難度 {difficulty} 的題目：{labels.get(difficulty, '')}"

    return f"""請根據以下教材內容產生 {num_choice} 題選擇題和 {num_tf} 題是非題。{diff_hint}

教材內容：
---
{text[:3000]}
---

請直接輸出 JSON 陣列，不要加其他說明文字。"""


def _parse_response(raw: str) -> list[dict]:
    """從 LLM 回應中解析 JSON 題目列表"""
    # 嘗試提取 JSON 區塊
    json_match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not json_match:
        return []

    try:
        questions = json.loads(json_match.group())
    except json.JSONDecodeError:
        return []

    valid = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        if q.get("type") not in ("choice", "truefalse"):
            continue
        if not q.get("content") or not q.get("answer"):
            continue
        if q.get("difficulty") not in (1, 2, 3):
            q["difficulty"] = 2  # 預設中等
        if q["type"] == "choice":
            if q["answer"] not in ("A", "B", "C", "D"):
                continue
            if not all(q.get(f"option_{k}") for k in "abcd"):
                continue
        elif q["type"] == "truefalse":
            if q["answer"] not in ("T", "F"):
                continue
            # 清除不需要的選項欄位
            for k in ("option_a", "option_b", "option_c", "option_d"):
                q.pop(k, None)
        valid.append(q)

    return valid


def generate_questions(
    text: str,
    chapter: str,
    source_file: str,
    num_choice: int = 3,
    num_tf: int = 2,
    difficulty: Optional[int] = None,
    model: str = MODEL,
) -> list[dict]:
    """從文本產生題目，回傳符合 database schema 的 dict 列表"""
    prompt = _build_prompt(text, num_choice, num_tf, difficulty)

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        options={"temperature": 0.7, "num_predict": 4096},
    )

    raw = response["message"]["content"]
    questions = _parse_response(raw)

    # 補充 chapter 與 source_file
    for q in questions:
        q["chapter"] = chapter
        q["source_file"] = source_file

    return questions


def generate_from_text_files(
    texts_dir: str = "data/texts",
    num_choice: int = 3,
    num_tf: int = 2,
    model: str = MODEL,
) -> list[dict]:
    """批次從 data/texts 中所有文本檔產生題目"""
    all_questions = []
    texts_path = Path(texts_dir)
    summary_path = texts_path / "_summary.json"

    # 讀取摘要以取得章節資訊
    chapters_map = {}
    if summary_path.exists():
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
            for fname, info in summary.items():
                chapters_map[fname] = info.get("chapter", fname.replace(".txt", ""))

    for txt_file in sorted(texts_path.glob("*.txt")):
        if txt_file.name.startswith("_"):
            continue

        text = txt_file.read_text(encoding="utf-8")
        if len(text.strip()) < 100:
            continue

        chapter = chapters_map.get(txt_file.name, txt_file.stem)
        print(f"  📝 正在為 [{chapter}] 產生題目 ({txt_file.name})...")

        questions = generate_questions(
            text=text,
            chapter=chapter,
            source_file=txt_file.name,
            num_choice=num_choice,
            num_tf=num_tf,
            model=model,
        )
        all_questions.extend(questions)
        print(f"     ✅ 產生 {len(questions)} 題")

    return all_questions


def insert_question_with_dedup(
    q: dict,
    threshold: float = 0.85,
    db_path: str = "data/questions.db",
    chroma_dir: str = "data/chroma",
) -> dict:
    """Insert question with semantic dedup check.
    Returns dict with inserted (bool), question_id, and similar_to if skipped."""
    similar = _embed_find(q["content"], threshold=threshold, chroma_dir=chroma_dir)
    if similar:
        return {
            "inserted": False,
            "question_id": None,
            "similar_to": similar[0],
        }

    qid = _db_insert(q, db_path=db_path)
    _embed_add(qid, q["content"], chroma_dir=chroma_dir)
    return {
        "inserted": True,
        "question_id": qid,
        "similar_to": None,
    }
