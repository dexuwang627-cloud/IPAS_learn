"""
批次補解析：用 Gemini 為缺少 explanation 的題目生成解析。
並行處理，付費 tier。
"""
import json
import os
import sys
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-2.5-flash"
DB_PATH = "data/questions.db"
MAX_WORKERS = 10
BATCH_SIZE = 5  # 一次送幾題給 Gemini


def get_missing_questions() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, type, content, option_a, option_b, option_c, option_d, answer, difficulty, chapter "
        "FROM questions WHERE explanation IS NULL OR explanation = ''"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build_explanation_prompt(questions: list[dict]) -> str:
    parts = []
    for q in questions:
        if q["type"] == "choice":
            parts.append(
                f"題目 #{q['id']}（選擇題，難度{q['difficulty']}，章節：{q['chapter']}）\n"
                f"Q: {q['content']}\n"
                f"A: {q['option_a']}\nB: {q['option_b']}\nC: {q['option_c']}\nD: {q['option_d']}\n"
                f"正確答案: {q['answer']}"
            )
        else:
            parts.append(
                f"題目 #{q['id']}（是非題，難度{q['difficulty']}，章節：{q['chapter']}）\n"
                f"Q: {q['content']}\n"
                f"正確答案: {'正確' if q['answer'] == 'T' else '錯誤'}"
            )

    return f"""請為以下 iPAS 考試題目撰寫解析。

規則：
1. 每題解析 1-3 句話
2. 選擇題：說明正確選項理由，並提及至少一個干擾選項為何錯
3. 是非題：說明該敘述為何正確或錯誤
4. 基於該章節的專業知識作答

請用以下 JSON 格式回覆，不要加其他文字：
[
  {{"id": 題號, "explanation": "解析內容"}},
  ...
]

{chr(10).join(parts)}"""


def generate_explanations(questions: list[dict]) -> list[dict]:
    prompt = build_explanation_prompt(questions)
    try:
        response = _client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=4096,
            ),
        )
        import re
        match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            time.sleep(15)
            try:
                response = _client.models.generate_content(
                    model=MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=4096,
                    ),
                )
                import re
                match = re.search(r'\[.*\]', response.text, re.DOTALL)
                if match:
                    return json.loads(match.group())
            except Exception:
                pass
        else:
            print(f"  Error: {e}")
    return []


def update_explanations(results: list[dict]) -> int:
    if not results:
        return 0
    conn = sqlite3.connect(DB_PATH)
    updated = 0
    for r in results:
        qid = r.get("id")
        exp = r.get("explanation", "")
        if qid and exp:
            conn.execute(
                "UPDATE questions SET explanation = ? WHERE id = ? AND (explanation IS NULL OR explanation = '')",
                (exp, qid),
            )
            updated += 1
    conn.commit()
    conn.close()
    return updated


def process_batch(batch: list[dict], batch_idx: int, total_batches: int) -> int:
    results = generate_explanations(batch)
    updated = update_explanations(results)
    ids = [q["id"] for q in batch]
    print(f"  [{batch_idx}/{total_batches}] IDs {ids[0]}-{ids[-1]}: "
          f"sent {len(batch)}, got {len(results)}, updated {updated}")
    return updated


def main():
    questions = get_missing_questions()
    total = len(questions)
    print(f"缺解析: {total} 題")

    # 分批
    batches = []
    for i in range(0, total, BATCH_SIZE):
        batches.append(questions[i:i + BATCH_SIZE])

    total_batches = len(batches)
    print(f"分為 {total_batches} 批，每批 {BATCH_SIZE} 題，{MAX_WORKERS} workers\n")

    total_updated = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for i, batch in enumerate(batches):
            future = executor.submit(process_batch, batch, i + 1, total_batches)
            futures[future] = i

        try:
            for future in as_completed(futures):
                total_updated += future.result()
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(0)

    # 驗證
    remaining = len(get_missing_questions())
    print(f"\n完成！更新 {total_updated} 題解析")
    print(f"仍缺解析: {remaining} 題")


if __name__ == "__main__":
    main()
