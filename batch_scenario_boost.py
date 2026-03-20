"""
批次補充情境題：L211、L212、模擬題
"""
import json
import os
import re
import sqlite3
import time
import uuid

from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-2.5-flash"
DB_PATH = "data/questions.db"


def call_gemini(prompt):
    for attempt in range(3):
        try:
            r = _client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.9, max_output_tokens=8192
                ),
            )
            return r.text
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                time.sleep(15 * (attempt + 1))
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


def insert_q(q):
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            """INSERT INTO questions
               (chapter, source_file, type, content, option_a, option_b, option_c, option_d,
                answer, difficulty, explanation, scenario_id, scenario_text, chapter_group, bank_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                q.get("chapter", ""),
                "batch_scenario_boost.py",
                q["type"],
                q["content"],
                q.get("option_a"),
                q.get("option_b"),
                q.get("option_c"),
                q.get("option_d"),
                q["answer"],
                q["difficulty"],
                q.get("explanation", ""),
                q.get("scenario_id"),
                q.get("scenario_text"),
                q["chapter_group"],
                "ipas-netzero-mid",
            ),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        print(f"DB err: {e}")
        return None
    finally:
        conn.close()


def gen_scenario(chapter, theme):
    prompt = (
        f"你是 iPAS 淨零碳規劃師中級考試出題專家。產生 2 組情境題組。\n\n"
        f"章節：{chapter}\n"
        f"主題方向：{theme}\n\n"
        "每組：\n"
        "- 一個台灣企業的具體情境（含公司名稱、產業、數據，120-200字）\n"
        "- 2 題 scenario_choice 子題，難度混合 1-3\n"
        "- 解析 ≥ 80 字\n\n"
        '直接輸出 JSON（不要 markdown code block）：\n'
        '[{"scenario_text": "...", "questions": [{"type": "scenario_choice", '
        '"content": "...", "option_a": "...", "option_b": "...", '
        '"option_c": "...", "option_d": "...", "answer": "B", '
        '"difficulty": 2, "explanation": "..."}]}]'
    )
    raw = call_gemini(prompt)
    scenarios = parse_json(raw)
    results = []
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        st = s.get("scenario_text", "")
        if not st:
            continue
        sid = str(uuid.uuid4())[:8]
        for sq in s.get("questions", []):
            if not isinstance(sq, dict):
                continue
            sq["type"] = "scenario_choice"
            if sq.get("answer") not in ("A", "B", "C", "D"):
                continue
            if not all(sq.get("option_" + k) for k in "abcd"):
                continue
            if sq.get("difficulty") not in (1, 2, 3):
                sq["difficulty"] = 2
            sq["scenario_id"] = sid
            sq["scenario_text"] = st
            sq["chapter_group"] = chapter
            sq["chapter"] = chapter
            results.append(sq)
    return results


def main():
    tasks = [
        (
            "L211 組織節能減碳策略",
            "ISO 50001 能源管理系統導入、能源績效指標 EnPI、能源基準 EnB",
        ),
        (
            "L211 組織節能減碳策略",
            "台灣能源管理法、能源大用戶義務、節能減碳策略規劃",
        ),
        (
            "L211 組織節能減碳策略",
            "企業碳盤查流程、國家淨零轉型路徑、能源統計分析",
        ),
        (
            "L212 節能技術應用與能源管理",
            "ESCO 節能績效保證、IPMVP 量測驗證、空調系統節能",
        ),
        (
            "模擬題與計算練習",
            "碳費計算（含高碳洩漏調整係數）、碳權抵換金額、免徵額",
        ),
        (
            "模擬題與計算練習",
            "節能投資回收期 SPP/NPV/IRR 計算、全生命週期成本 LCC",
        ),
        (
            "模擬題與計算練習",
            "範疇三碳排放計算、碳足跡盤查、活動數據與排放係數",
        ),
    ]

    total_ins = 0
    for chapter, theme in tasks:
        qs = gen_scenario(chapter, theme)
        for q in qs:
            if insert_q(q):
                total_ins += 1
        print(f"  [情境] {chapter} ({theme[:30]}): +{len(qs)}")
        time.sleep(3)

    print(f"\n總插入: {total_ins}")

    # 驗證
    conn = sqlite3.connect(DB_PATH)
    print(f"總題數: {conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0]}")
    for ch in [
        "L211 組織節能減碳策略",
        "L212 節能技術應用與能源管理",
        "模擬題與計算練習",
    ]:
        r = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE chapter_group=? AND type='scenario_choice'",
            (ch,),
        ).fetchone()
        print(f"  {ch} 情境題: {r[0]}")
    conn.close()


if __name__ == "__main__":
    main()
