"""
平衡 L212 的 T/F 比例：補 F 題。
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


def call_gemini(prompt):
    for a in range(3):
        try:
            r = _client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.9, max_output_tokens=4096
                ),
            )
            return r.text
        except Exception as e:
            if "429" in str(e):
                time.sleep(15 * (a + 1))
            else:
                print(f"Error: {str(e)[:80]}")
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


def insert_tf(content, difficulty, explanation, chapter_group):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO questions
               (chapter, source_file, type, content, answer, difficulty,
                explanation, chapter_group, bank_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                chapter_group,
                "batch_tf_balance.py",
                "truefalse",
                content,
                "F",
                difficulty,
                explanation,
                chapter_group,
                "ipas-netzero-mid",
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"DB err: {e}")
        return False
    finally:
        conn.close()


def main():
    prompt = (
        "你是 iPAS 淨零碳規劃師中級考試出題專家。\n"
        "請產生 10 題答案為「錯誤（F）」的是非題。\n\n"
        "章節：L212 節能技術應用與能源管理\n"
        "涵蓋主題（每題不同主題）：\n"
        "1. 鍋爐燃燒效率與廢熱回收\n"
        "2. 高效率馬達 IE3/IE4/IE5 等級\n"
        "3. LED 照明與智慧照明控制\n"
        "4. 冰水主機 COP 與能效比\n"
        "5. 空壓系統節能（變頻、洩漏）\n"
        "6. ESCO 節能績效保證合約\n"
        "7. IPMVP 量測驗證方法\n"
        "8. 建築外殼隔熱與 ENVLOAD\n"
        "9. 電力需量管理與契約容量\n"
        "10. 熱泵系統與熱回收\n\n"
        "規則：\n"
        "- 所有答案必須是 F\n"
        "- 設計看起來合理但有錯誤的敘述\n"
        "- 常見陷阱：數字錯誤、因果倒置、概念混淆\n"
        "- 混合難度 1/2/3\n"
        "- 解析 ≥ 80 字\n\n"
        "直接輸出 JSON 陣列（不要 markdown code block）：\n"
        '[{"type": "truefalse", "content": "...", "answer": "F", '
        '"difficulty": 2, "explanation": "此敘述錯誤，因為..."}]'
    )

    raw = call_gemini(prompt)
    print(f"Raw response length: {len(raw)}")
    questions = parse_json(raw)
    print(f"Parsed questions: {len(questions)}")

    cnt = 0
    for q in questions:
        if not isinstance(q, dict):
            continue
        if q.get("answer") != "F":
            continue
        diff = q.get("difficulty", 2)
        if diff not in (1, 2, 3):
            diff = 2
        content = q.get("content", "")
        explanation = q.get("explanation", "")
        if content and explanation:
            if insert_tf(content, diff, explanation, "L212 節能技術應用與能源管理"):
                cnt += 1

    print(f"L212 F 題: +{cnt}")

    # 驗證
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute(
        """SELECT
           SUM(CASE WHEN answer='T' THEN 1 ELSE 0 END) as T,
           SUM(CASE WHEN answer='F' THEN 1 ELSE 0 END) as F,
           ROUND(100.0 * SUM(CASE WHEN answer='T' THEN 1 ELSE 0 END) / COUNT(*), 1) as T_pct
           FROM questions
           WHERE type='truefalse' AND chapter_group='L212 節能技術應用與能源管理'"""
    ).fetchone()
    print(f"L212 T/F: T={r[0]}, F={r[1]}, T%={r[2]}")

    r2 = conn.execute(
        """SELECT answer, COUNT(*),
           ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM questions WHERE type='truefalse'), 1)
           FROM questions WHERE type='truefalse' GROUP BY answer"""
    ).fetchall()
    for ans, cnt, pct in r2:
        print(f"整體 {ans}: {cnt} ({pct}%)")
    print(f"總題數: {conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main()
