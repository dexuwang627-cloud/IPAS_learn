"""
批次修復偏短解析：重新用 Gemini 生成 ≥ 80 字的解析。
針對 LENGTH(explanation) < 50 的題目。
"""
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-2.5-flash"
DB_PATH = "data/questions.db"
MAX_WORKERS = 5
BATCH_SIZE = 5
MIN_EXPLANATION_LEN = 80


def get_short_explanation_questions() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, type, content, option_a, option_b, option_c, option_d, "
        "answer, difficulty, chapter_group, explanation "
        "FROM questions WHERE LENGTH(explanation) < 50"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build_prompt(questions: list[dict]) -> str:
    parts = []
    for q in questions:
        chapter = q["chapter_group"] or "未分類"
        if q["type"] in ("choice", "scenario_choice", "multichoice"):
            parts.append(
                f"題目 #{q['id']}（{q['type']}，難度{q['difficulty']}，章節：{chapter}）\n"
                f"Q: {q['content']}\n"
                f"A: {q['option_a']}\nB: {q['option_b']}\nC: {q['option_c']}\nD: {q['option_d']}\n"
                f"正確答案: {q['answer']}\n"
                f"原解析（太短需改善）: {q['explanation']}"
            )
        else:
            parts.append(
                f"題目 #{q['id']}（是非題，難度{q['difficulty']}，章節：{chapter}）\n"
                f"Q: {q['content']}\n"
                f"正確答案: {'正確' if q['answer'] == 'T' else '錯誤'}\n"
                f"原解析（太短需改善）: {q['explanation']}"
            )

    return f"""請為以下 iPAS 淨零碳規劃師考試題目重新撰寫「完整」的解析。

原有解析太短或被截斷，請重新撰寫。

嚴格規則：
1. 每題解析必須 80 字以上（繁體中文字數）
2. 選擇題：先說明正確選項的理由，再解釋至少一個干擾選項為何不正確
3. 是非題：說明該敘述為何正確或錯誤，並補充相關專業知識
4. 使用繁體中文，語氣專業但易懂
5. 引用具體的法規條文、數據或技術原理來支撐解析

請用以下 JSON 格式回覆，不要加其他文字：
[
  {{"id": 題號, "explanation": "解析內容"}},
  ...
]

{chr(10).join(parts)}"""


def generate_explanations(questions: list[dict]) -> list[dict]:
    prompt = build_prompt(questions)
    try:
        response = _client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=8192,
            ),
        )
        match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            print(f"  Rate limited, waiting 20s...")
            time.sleep(20)
            try:
                response = _client.models.generate_content(
                    model=MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=8192,
                    ),
                )
                match = re.search(r'\[.*\]', response.text, re.DOTALL)
                if match:
                    return json.loads(match.group())
            except Exception:
                pass
        else:
            print(f"  Error: {e}")
    return []


def update_explanations(results: list[dict]) -> tuple[int, int]:
    if not results:
        return 0, 0
    conn = sqlite3.connect(DB_PATH)
    updated = 0
    still_short = 0
    for r in results:
        qid = r.get("id")
        exp = r.get("explanation", "")
        if qid and exp and len(exp) >= MIN_EXPLANATION_LEN:
            conn.execute(
                "UPDATE questions SET explanation = ? WHERE id = ?",
                (exp, qid),
            )
            updated += 1
        elif qid and exp:
            still_short += 1
            print(f"    ID {qid}: 新解析仍太短 ({len(exp)} 字)，跳過")
    conn.commit()
    conn.close()
    return updated, still_short


def process_batch(batch: list[dict], batch_idx: int, total_batches: int) -> tuple[int, int]:
    results = generate_explanations(batch)
    updated, still_short = update_explanations(results)
    ids = [q["id"] for q in batch]
    print(f"  [{batch_idx}/{total_batches}] IDs {ids}: "
          f"sent {len(batch)}, got {len(results)}, updated {updated}, still_short {still_short}")
    return updated, still_short


def main():
    questions = get_short_explanation_questions()
    total = len(questions)
    print(f"偏短解析（< 50 字）: {total} 題")

    if total == 0:
        print("沒有需要修復的題目！")
        return

    batches = [questions[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    total_batches = len(batches)
    print(f"分為 {total_batches} 批，每批 {BATCH_SIZE} 題，{MAX_WORKERS} workers\n")

    total_updated = 0
    total_still_short = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for i, batch in enumerate(batches):
            future = executor.submit(process_batch, batch, i + 1, total_batches)
            futures[future] = i

        try:
            for future in as_completed(futures):
                u, s = future.result()
                total_updated += u
                total_still_short += s
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(0)

    # 驗證
    remaining = len(get_short_explanation_questions())
    print(f"\n完成！")
    print(f"  更新: {total_updated} 題")
    print(f"  仍太短（Gemini 回傳不足 80 字）: {total_still_short} 題")
    print(f"  剩餘偏短: {remaining} 題")


if __name__ == "__main__":
    main()
