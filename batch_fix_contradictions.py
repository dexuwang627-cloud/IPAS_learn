"""
修復答案/解析矛盾的題目。
對於每題，提供完整題目資訊給 Gemini，讓它判斷正確答案並重新撰寫解析。
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

# 需要修復的題目 ID
FIX_IDS = [233, 235, 304, 324, 384, 471, 483, 727, 803, 846]


def load_questions(ids):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT * FROM questions WHERE id IN ({placeholders})", ids
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build_prompt(questions):
    parts = []
    for q in questions:
        parts.append(
            f"題目 #{q['id']}（選擇題，難度{q['difficulty']}）\n"
            f"Q: {q['content']}\n"
            f"A: {q['option_a']}\n"
            f"B: {q['option_b']}\n"
            f"C: {q['option_c']}\n"
            f"D: {q['option_d']}\n"
            f"目前答案: {q['answer']}\n"
            f"目前解析: {q['explanation']}\n"
        )

    return (
        "以下選擇題的「答案」與「解析」互相矛盾。\n"
        "請重新分析每題，判斷正確答案，並重寫解析。\n\n"
        "規則：\n"
        "1. 仔細閱讀題目和四個選項，判斷哪個選項才是正確的\n"
        "2. 參考現有解析的推理邏輯（通常解析的推理是對的，但引用的選項字母搞混了）\n"
        "3. 重寫解析，確保引用的選項字母與實際選項內容一致\n"
        "4. 解析 ≥ 80 字\n"
        "5. 選擇題解析須說明正確選項理由，並提及至少一個干擾選項為何錯\n\n"
        "直接輸出 JSON 陣列（不要 markdown code block）：\n"
        '[{"id": 題號, "correct_answer": "正確的選項字母", '
        '"explanation": "重寫的解析"}]\n\n'
        + "\n---\n".join(parts)
    )


def main():
    questions = load_questions(FIX_IDS)
    print(f"載入 {len(questions)} 題需修復")

    prompt = build_prompt(questions)
    print("呼叫 Gemini...")

    for attempt in range(3):
        try:
            response = _client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=12000,
                ),
            )
            break
        except Exception as e:
            if "429" in str(e):
                time.sleep(15 * (attempt + 1))
            else:
                print(f"Error: {e}")
                return

    raw = response.text
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        print("無法解析 Gemini 回應")
        print(raw[:500])
        return

    results = json.loads(m.group())
    print(f"收到 {len(results)} 題修正")

    conn = sqlite3.connect(DB_PATH)
    for r in results:
        qid = r.get("id")
        new_answer = r.get("correct_answer", "")
        new_exp = r.get("explanation", "")

        if not qid or not new_answer or not new_exp:
            continue

        if new_answer not in ("A", "B", "C", "D"):
            print(f"  ID {qid}: 答案 '{new_answer}' 不合法，跳過")
            continue

        # 查詢原始答案
        old = conn.execute(
            "SELECT answer FROM questions WHERE id = ?", (qid,)
        ).fetchone()
        old_answer = old[0] if old else "?"

        conn.execute(
            "UPDATE questions SET answer = ?, explanation = ? WHERE id = ?",
            (new_answer, new_exp, qid),
        )
        changed = "CHANGED" if new_answer != old_answer else "kept"
        print(f"  ID {qid}: {old_answer} → {new_answer} ({changed}), 解析已更新")

    conn.commit()
    conn.close()
    print("\n修復完成！")


if __name__ == "__main__":
    main()
