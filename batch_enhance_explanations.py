"""
強化解析品質：
1. 解析 < 80 字的題目 → 重新生成完整解析
2. 計算題缺步驟 → 重新生成含詳細計算過程的解析
"""
import json
import os
import re
import sqlite3
import time

from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-2.5-flash"
DB_PATH = "data/questions.db"
BATCH_SIZE = 5
MAX_WORKERS = 5


def call_gemini(prompt, max_tokens=8192):
    for attempt in range(3):
        try:
            r = _client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3, max_output_tokens=max_tokens,
                ),
            )
            return r.text
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                time.sleep(15 * (attempt + 1))
            else:
                print(f"    Error: {str(e)[:80]}")
                return ""
    return ""


def parse_json(text):
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return []


# ============================================================
# Phase 1: 解析 < 80 字
# ============================================================

SHORT_EXP_PROMPT = """請為以下 iPAS 考試題目重新撰寫「完整」的解析。原有解析太短。

嚴格規則：
1. 每題解析必須 80 字以上
2. 選擇題：先說明正確選項的理由，再解釋至少一個干擾選項為何不正確
3. 是非題：說明該敘述為何正確或錯誤，並補充相關專業知識
4. 引用具體的法規條文、數據或技術原理

直接輸出 JSON（不要 markdown code block）：
[{{"id": 題號, "explanation": "新解析"}}]

{questions_text}"""


def fix_short_explanations():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, type, content, option_a, option_b, option_c, option_d, "
        "answer, difficulty, chapter_group, explanation "
        "FROM questions WHERE LENGTH(explanation) < 80"
    ).fetchall()
    conn.close()

    questions = [dict(r) for r in rows]
    total = len(questions)
    print(f"\n=== Phase 1: 修復偏短解析 ({total} 題) ===")

    if total == 0:
        print("  無需修復")
        return

    batches = [questions[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    updated = 0

    for bi, batch in enumerate(batches):
        parts = []
        for q in batch:
            if q["type"] in ("choice", "scenario_choice", "multichoice"):
                parts.append(
                    f"題目 #{q['id']}（{q['type']}，難度{q['difficulty']}，{q['chapter_group']}）\n"
                    f"Q: {q['content']}\n"
                    f"A: {q['option_a']}\nB: {q['option_b']}\nC: {q['option_c']}\nD: {q['option_d']}\n"
                    f"正確答案: {q['answer']}\n原解析: {q['explanation']}"
                )
            else:
                parts.append(
                    f"題目 #{q['id']}（是非題，難度{q['difficulty']}，{q['chapter_group']}）\n"
                    f"Q: {q['content']}\n"
                    f"正確答案: {'正確' if q['answer'] == 'T' else '錯誤'}\n原解析: {q['explanation']}"
                )

        prompt = SHORT_EXP_PROMPT.format(questions_text="\n---\n".join(parts))
        raw = call_gemini(prompt)
        results = parse_json(raw)

        conn = sqlite3.connect(DB_PATH)
        for r in results:
            qid = r.get("id")
            exp = r.get("explanation", "")
            if qid and exp and len(exp) >= 80:
                conn.execute("UPDATE questions SET explanation = ? WHERE id = ?", (exp, qid))
                updated += 1
        conn.commit()
        conn.close()

        print(f"  [{bi + 1}/{len(batches)}] updated {len(results)}")
        time.sleep(1)

    remaining = sqlite3.connect(DB_PATH).execute(
        "SELECT COUNT(*) FROM questions WHERE LENGTH(explanation) < 80"
    ).fetchone()[0]
    print(f"  完成: {updated} 題已更新, 剩餘 {remaining} 題 < 80 字")


# ============================================================
# Phase 2: 計算題加詳細步驟
# ============================================================

CALC_EXP_PROMPT = """以下是 iPAS 考試的計算/數據類題目，但解析缺少詳細的計算過程。
請重寫解析，必須包含：

1. **列出已知條件**（從題目提取的數據）
2. **寫出計算公式**
3. **代入數值逐步計算**（每一步都要列出）
4. **得出結果並對應選項**
5. **簡要說明為何其他選項不正確**

解析長度至少 120 字。使用 × ÷ = 等數學符號。

直接輸出 JSON（不要 markdown code block）：
[{{"id": 題號, "explanation": "新解析（含完整計算步驟）"}}]

{questions_text}"""


def fix_calc_explanations():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, type, content, option_a, option_b, option_c, option_d,
                  answer, difficulty, chapter_group, explanation
           FROM questions
           WHERE difficulty >= 2
           AND (content LIKE '%多少%' OR content LIKE '%計算%' OR content LIKE '%數值%'
             OR content LIKE '%公噸%' OR content LIKE '%萬元%' OR content LIKE '%kW%'
             OR content LIKE '%回收期%' OR content LIKE '%NPV%' OR content LIKE '%IRR%'
             OR content LIKE '%百分%' OR content LIKE '%噸%' OR content LIKE '%度%')
           AND type IN ('choice', 'scenario_choice')
           AND explanation NOT LIKE '%=%'
           AND explanation NOT LIKE '%×%'
           AND explanation NOT LIKE '%計算%'
           AND explanation NOT LIKE '%公式%'
           AND explanation NOT LIKE '%代入%'
           AND LENGTH(explanation) < 200"""
    ).fetchall()
    conn.close()

    questions = [dict(r) for r in rows]
    total = len(questions)
    print(f"\n=== Phase 2: 計算題加步驟 ({total} 題) ===")

    if total == 0:
        print("  無需修復")
        return

    batches = [questions[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    updated = 0

    for bi, batch in enumerate(batches):
        parts = []
        for q in batch:
            parts.append(
                f"題目 #{q['id']}（{q['type']}，難度{q['difficulty']}，{q['chapter_group']}）\n"
                f"Q: {q['content']}\n"
                f"A: {q['option_a']}\nB: {q['option_b']}\nC: {q['option_c']}\nD: {q['option_d']}\n"
                f"正確答案: {q['answer']}\n現有解析: {q['explanation']}"
            )

        prompt = CALC_EXP_PROMPT.format(questions_text="\n---\n".join(parts))
        raw = call_gemini(prompt, max_tokens=12000)
        results = parse_json(raw)

        conn = sqlite3.connect(DB_PATH)
        for r in results:
            qid = r.get("id")
            exp = r.get("explanation", "")
            if qid and exp and len(exp) >= 100:
                conn.execute("UPDATE questions SET explanation = ? WHERE id = ?", (exp, qid))
                updated += 1
        conn.commit()
        conn.close()

        print(f"  [{bi + 1}/{len(batches)}] updated {len(results)}")
        time.sleep(1)

    print(f"  完成: {updated} 題已更新")


def main():
    print("=" * 60)
    print("解析品質強化")
    print("=" * 60)

    fix_short_explanations()
    fix_calc_explanations()

    # Final stats
    conn = sqlite3.connect(DB_PATH)
    print("\n=== 最終統計 ===")

    r = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE LENGTH(explanation) < 80"
    ).fetchone()
    print(f"解析 < 80 字: {r[0]}")

    r = conn.execute("""
        SELECT
          CASE
            WHEN LENGTH(explanation) < 80 THEN '< 80字'
            WHEN LENGTH(explanation) BETWEEN 80 AND 120 THEN '80-120字'
            WHEN LENGTH(explanation) BETWEEN 121 AND 200 THEN '121-200字'
            WHEN LENGTH(explanation) > 200 THEN '> 200字'
          END as range,
          COUNT(*) as cnt
        FROM questions GROUP BY range ORDER BY cnt DESC
    """).fetchall()
    for rng, cnt in r:
        print(f"  {rng}: {cnt}")

    conn.close()


if __name__ == "__main__":
    main()
