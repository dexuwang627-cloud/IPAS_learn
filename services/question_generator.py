"""
Question Generator Service
使用 Gemini API 從文本自動產生 iPAS 考試題目
"""
import json
import os
import re
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from database import insert_question as _db_insert
from services.embedding_service import add_question as _embed_add, find_similar as _embed_find

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MODEL = "gemini-2.5-flash"

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
    "difficulty": 1,
    "explanation": "說明正確答案的理由，並簡述干擾選項為何錯誤"
  },
  {
    "type": "truefalse",
    "content": "題目內容",
    "answer": "T",
    "difficulty": 2,
    "explanation": "說明該敘述為何正確或錯誤，引用教材中的具體內容"
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
9. explanation 必須基於教材內容，1-3 句話
10. 選擇題的 explanation 須說明正確選項理由，並提及至少一個干擾選項為何錯
11. 是非題的 explanation 須說明該敘述為何正確或錯誤
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


def _normalize_question(q: dict) -> Optional[dict]:
    """將各種 LLM 回傳格式正規化為統一 schema"""
    if not isinstance(q, dict):
        return None

    # 正規化 type
    raw_type = str(q.get("type", "")).lower().replace("_", "").replace("-", "")
    if raw_type in ("choice", "multiplechoice"):
        q["type"] = "choice"
    elif raw_type in ("truefalse", "trueorfalse", "tf"):
        q["type"] = "truefalse"
    else:
        return None

    # 正規化 content（有些模型用 "question" 而非 "content"）
    if "content" not in q and "question" in q:
        q["content"] = q.pop("question")
    if not q.get("content"):
        return None

    # 正規化 answer
    answer = q.get("answer")
    if isinstance(answer, bool):
        q["answer"] = "T" if answer else "F"
    elif isinstance(answer, str):
        q["answer"] = answer.strip().upper()
    else:
        return None

    # 正規化 options（有些模型用 {"A": "...", "B": "..."} 物件）
    if "options" in q and isinstance(q["options"], dict):
        for key in ("A", "B", "C", "D"):
            field = f"option_{key.lower()}"
            if field not in q and key in q["options"]:
                q[field] = q["options"][key]
        del q["options"]

    # 正規化 difficulty
    if q.get("difficulty") not in (1, 2, 3):
        q["difficulty"] = 2

    # 正規化 explanation（有些模型用 "reference"）
    if "explanation" not in q or not q.get("explanation"):
        q["explanation"] = q.pop("reference", None)

    return q


def _parse_response(raw: str) -> list[dict]:
    """從 LLM 回應中解析 JSON 題目列表"""
    json_match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not json_match:
        return []

    try:
        questions = json.loads(json_match.group())
    except json.JSONDecodeError:
        return []

    valid = []
    for q in questions:
        normalized = _normalize_question(q)
        if normalized is None:
            continue

        if normalized["type"] == "choice":
            if normalized["answer"] not in ("A", "B", "C", "D"):
                continue
            if not all(normalized.get(f"option_{k}") for k in "abcd"):
                continue
        elif normalized["type"] == "truefalse":
            if normalized["answer"] not in ("T", "F"):
                continue
            for k in ("option_a", "option_b", "option_c", "option_d"):
                normalized.pop(k, None)

        valid.append(normalized)

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

    response = _client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7,
            max_output_tokens=4096,
        ),
    )

    raw = response.text
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
