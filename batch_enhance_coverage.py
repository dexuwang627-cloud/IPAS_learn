"""
批次增強題庫覆蓋率：
1. 各章節增加情境題 + 多選題 (Task 4)
2. T/F 比例偏斜章節補 F 題 (Task 5)
3. L211 補強 (Task 8)

使用 text 檔案（不需下載 PDF），直接呼叫 Gemini API。
"""
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-2.5-flash"
DB_PATH = "data/questions.db"
TEXTS_DIR = Path("data/texts")
MAX_WORKERS = 5

# === 章節 → text 檔案對應 ===
CHAPTER_TEXTS = {
    "L211 組織節能減碳策略": [
        "L211_組織節能減碳策略_V1整理.txt",
        "2026 iPAS 淨零中級 科目一 L211 組織節能減碳策略  V1整理 CCChen 20260120_e0d707.txt",
    ],
    "L212 節能技術應用與能源管理": [
        "L212_節能技術應用與能源管理_V1整理.txt",
        "2026 iPAS 淨零中級 科目一  L212 節能技術應用與能源管理  V1整理 CCChen 20260120_0e8899.txt",
        "L21201_公用設施節能_鄭惠如.txt",
        "L21202_節能技術投資_黃文弘.txt",
    ],
    "L213 再生能源與綠電導入": [
        "L213_再生能源與綠電導入_V1整理.txt",
        "2026 iPAS 淨零中級 科目一 L213  再生能源與綠電導入  V1整理 CCChen 20260120_f74f9a.txt",
    ],
    "L221 碳管理法規與國際倡議": [
        "iPAS 淨零（中級）L221 國內法規彙整  CCChen  20260117_c2b712.txt",
        "2026淨零中級 L221國際倡議的關鍵專有名詞 彙整  CCChen 20260118_1af66f.txt",
        "2026淨零中級 L221國內法規的關鍵專有名詞 彙整 CCChen 20260118_fe0fd8.txt",
    ],
    "L222 碳移除與負碳技術": [
        "L22201-國內外自願減量專案與抵換制度_52e8f3.txt",
        "L22202-碳移除技術與術語詳細彙總表_f8605f.txt",
        "L22204-內部碳定價與碳資產管理_53e581.txt",
    ],
    "L223 供應鏈碳管理": [
        "L22301-GHG Protocol_436ccc.txt",
        "4_Scope3_Calculation_Guidance_價值鏈排放_e5e44b.txt",
        "EcoVadis 綜合簡報_346cc0.txt",
    ],
    "核心教材 氣候變遷與碳足跡": [
        "1_ghg_protocol_chinese_企業標準_0c4e4b.txt",
        "GHG protocol 簡介_ef1f0f.txt",
    ],
    "模擬題與計算練習": [
        "L212_節能技術應用與能源管理_V1整理.txt",
        "L22204-內部碳定價與碳資產管理_53e581.txt",
    ],
}


def load_chapter_text(chapter: str, max_chars: int = 6000) -> str:
    """載入章節對應的 text 檔案內容"""
    files = CHAPTER_TEXTS.get(chapter, [])
    combined = ""
    for fname in files:
        path = TEXTS_DIR / fname
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="ignore")
            combined += content + "\n\n"
        if len(combined) >= max_chars:
            break
    return combined[:max_chars]


def call_gemini(prompt: str, max_tokens: int = 8192) -> str:
    """呼叫 Gemini API，帶重試"""
    for attempt in range(3):
        try:
            response = _client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.9,
                    max_output_tokens=max_tokens,
                ),
            )
            return response.text
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "503" in err:
                wait = 15 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    Error: {err[:100]}")
                return ""
    return ""


def parse_json_array(text: str) -> list[dict]:
    """從 Gemini 回傳文字中提取 JSON 陣列"""
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []


def insert_question(q: dict) -> int | None:
    """插入題目到 DB，回傳 question_id 或 None"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            """INSERT INTO questions
               (chapter, source_file, type, content, option_a, option_b, option_c, option_d,
                answer, difficulty, explanation, scenario_id, scenario_text, chapter_group, bank_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                q.get("chapter", ""),
                q.get("source_file", "batch_enhance_coverage.py"),
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
        print(f"    DB error: {e}")
        return None
    finally:
        conn.close()


# ============================================================
# Task 4: 情境題 + 多選題
# ============================================================

SCENARIO_PROMPT = """你是 iPAS 淨零碳規劃師中級考試的出題專家。
請根據以下教材重點，產生 2 組「情境題組」。

教材重點（章節：{chapter}）：
---
{text}
---

情境題規則：
- 先描述一個具體的台灣企業情境（120-200 字），包含公司類型、產業、排放數據、面臨的問題
- 針對這個情境出 2 題子題（單選）
- 第一題考基本判斷（難度 1-2），第二題考分析或計算（難度 2-3）
- 解析必須 ≥ 80 字，引用具體法規、數據或技術原理

JSON 格式（直接輸出，不要其他文字）：
[
  {{
    "scenario_text": "某企業情境描述...",
    "questions": [
      {{
        "type": "scenario_choice",
        "content": "根據上述情境，...",
        "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...",
        "answer": "B",
        "difficulty": 1,
        "explanation": "解析..."
      }},
      {{
        "type": "scenario_choice",
        "content": "...",
        "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...",
        "answer": "C",
        "difficulty": 3,
        "explanation": "解析..."
      }}
    ]
  }}
]"""

MULTICHOICE_PROMPT = """你是 iPAS 淨零碳規劃師中級考試的出題專家。
請根據以下教材重點，產生 3 題「複選題」。

教材重點（章節：{chapter}）：
---
{text}
---

複選題規則：
- 每題有 A/B/C/D 四個選項
- 正確答案為 2-3 個選項（不能只有 1 個，也不能全選）
- 題目要明確寫「下列哪些敘述正確？（複選）」
- 干擾選項要有合理性
- 混合難度 1/2/3
- 解析必須 ≥ 80 字，逐一說明各選項正確或錯誤的原因

JSON 格式（直接輸出，不要其他文字）：
[
  {{
    "type": "multichoice",
    "content": "下列關於...的敘述，哪些正確？（複選）",
    "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...",
    "answer": "AC",
    "difficulty": 2,
    "explanation": "A 正確因為...，C 正確因為...。B 錯誤因為...，D 錯誤因為..."
  }}
]"""


def generate_scenario_questions(chapter: str, text: str) -> list[dict]:
    prompt = SCENARIO_PROMPT.format(chapter=chapter, text=text[:4000])
    raw = call_gemini(prompt)
    scenarios = parse_json_array(raw)

    results = []
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        scenario_text = s.get("scenario_text", "")
        if not scenario_text:
            continue
        scenario_id = str(uuid.uuid4())[:8]
        for sq in s.get("questions", []):
            if not isinstance(sq, dict):
                continue
            sq_type = sq.get("type", "scenario_choice")
            if sq_type not in ("scenario_choice", "scenario_multichoice"):
                sq["type"] = "scenario_choice"
            ans = sq.get("answer", "")
            if sq.get("type") == "scenario_choice" and ans not in ("A", "B", "C", "D"):
                continue
            if not all(sq.get(f"option_{k}") for k in "abcd"):
                continue
            sq["scenario_id"] = scenario_id
            sq["scenario_text"] = scenario_text
            sq["chapter_group"] = chapter
            sq["chapter"] = chapter
            sq["source_file"] = "batch_enhance_coverage.py"
            results.append(sq)
    return results


def generate_multichoice_questions(chapter: str, text: str) -> list[dict]:
    prompt = MULTICHOICE_PROMPT.format(chapter=chapter, text=text[:4000])
    raw = call_gemini(prompt)
    questions = parse_json_array(raw)

    results = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        q["type"] = "multichoice"
        ans = q.get("answer", "")
        if not (2 <= len(ans) <= 3 and all(c in "ABCD" for c in ans)):
            continue
        if not all(q.get(f"option_{k}") for k in "abcd"):
            continue
        q["chapter_group"] = chapter
        q["chapter"] = chapter
        q["source_file"] = "batch_enhance_coverage.py"
        results.append(q)
    return results


# ============================================================
# Task 5: 平衡 T/F（生成 F 題）
# ============================================================

FALSE_TF_PROMPT = """你是 iPAS 淨零碳規劃師中級考試的出題專家。
請根據以下教材重點，產生 {num} 題「答案為錯誤（F）」的是非題。

教材重點（章節：{chapter}）：
---
{text}
---

規則：
- 所有題目的正確答案必須是 F（錯誤）
- 題目要設計成看起來合理但實際上有錯誤的敘述
- 常見陷阱：數字錯誤、概念混淆、因果倒置、範圍錯誤
- 混合難度 1/2/3
- 解析必須 ≥ 80 字，說明該敘述哪裡錯誤以及正確的說法

JSON 格式（直接輸出，不要其他文字）：
[
  {{
    "type": "truefalse",
    "content": "看起來合理但實際錯誤的敘述...",
    "answer": "F",
    "difficulty": 2,
    "explanation": "此敘述錯誤，因為..."
  }}
]"""


def generate_false_tf(chapter: str, text: str, num: int = 5) -> list[dict]:
    prompt = FALSE_TF_PROMPT.format(chapter=chapter, text=text[:4000], num=num)
    raw = call_gemini(prompt)
    questions = parse_json_array(raw)

    results = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        q["type"] = "truefalse"
        if q.get("answer") != "F":
            continue
        if q.get("difficulty") not in (1, 2, 3):
            q["difficulty"] = 2
        q["chapter_group"] = chapter
        q["chapter"] = chapter
        q["source_file"] = "batch_enhance_coverage.py"
        results.append(q)
    return results


# ============================================================
# Task 8: L211 補強（更多選擇題+是非題）
# ============================================================

L211_BOOST_PROMPT = """你是 iPAS 淨零碳規劃師中級考試的出題專家。
請根據以下教材重點，產生 {num_choice} 題選擇題和 {num_tf} 題是非題。

教材重點（章節：L211 組織節能減碳策略）：
---
{text}
---

規則：
1. 選擇題 answer 只能是 A/B/C/D，四個選項都要有
2. 是非題 answer 只能是 T/F，且 T 和 F 的比例要均衡
3. 混合難度 1/2/3
4. 解析必須 ≥ 80 字
5. 選擇題解析：說明正確選項理由，並提及至少一個干擾選項為何錯
6. 是非題解析：說明該敘述為何正確或錯誤
7. 題目要覆蓋不同知識點：ISO 50001、能源管理法、能源績效指標、能源基準、碳盤查流程

JSON 格式（直接輸出，不要其他文字）：
[
  {{
    "type": "choice",
    "content": "題目",
    "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...",
    "answer": "A",
    "difficulty": 1,
    "explanation": "解析..."
  }},
  {{
    "type": "truefalse",
    "content": "敘述...",
    "answer": "T",
    "difficulty": 2,
    "explanation": "解析..."
  }}
]"""


def generate_l211_boost(text: str, num_choice: int = 5, num_tf: int = 5) -> list[dict]:
    prompt = L211_BOOST_PROMPT.format(text=text[:5000], num_choice=num_choice, num_tf=num_tf)
    raw = call_gemini(prompt, max_tokens=12000)
    questions = parse_json_array(raw)

    results = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        qtype = q.get("type")
        if qtype == "choice":
            if q.get("answer") not in ("A", "B", "C", "D"):
                continue
            if not all(q.get(f"option_{k}") for k in "abcd"):
                continue
        elif qtype == "truefalse":
            if q.get("answer") not in ("T", "F"):
                continue
        else:
            continue
        if q.get("difficulty") not in (1, 2, 3):
            q["difficulty"] = 2
        q["chapter_group"] = "L211 組織節能減碳策略"
        q["chapter"] = "L211 組織節能減碳策略"
        q["source_file"] = "batch_enhance_coverage.py"
        results.append(q)
    return results


# ============================================================
# Main
# ============================================================

def run_task(task_name: str, generate_fn, chapter: str, **kwargs) -> dict:
    """執行單一生成任務"""
    text = load_chapter_text(chapter)
    if not text:
        print(f"  [{task_name}] {chapter}: 無 text 檔案，跳過")
        return {"generated": 0, "inserted": 0}

    questions = generate_fn(chapter=chapter, text=text, **kwargs) if "chapter" in generate_fn.__code__.co_varnames else generate_fn(text=text, **kwargs)
    inserted = 0
    for q in questions:
        qid = insert_question(q)
        if qid:
            inserted += 1

    print(f"  [{task_name}] {chapter}: 生成 {len(questions)}, 插入 {inserted}")
    return {"generated": len(questions), "inserted": inserted}


def main():
    print("=" * 60)
    print("iPAS 題庫增強")
    print("=" * 60)

    total_gen = 0
    total_ins = 0

    # === Task 4: 各章節增加情境題 + 多選題 ===
    print("\n--- Task 4: 增加情境題 + 多選題 ---")
    chapters_for_sc_mc = [
        "L211 組織節能減碳策略",
        "L212 節能技術應用與能源管理",
        "L213 再生能源與綠電導入",
        "L221 碳管理法規與國際倡議",
        "L222 碳移除與負碳技術",
        "L223 供應鏈碳管理",
        "核心教材 氣候變遷與碳足跡",
        "模擬題與計算練習",
    ]

    for chapter in chapters_for_sc_mc:
        text = load_chapter_text(chapter)
        if not text:
            print(f"  {chapter}: 無 text 檔案，跳過")
            continue

        # 情境題
        sc_questions = generate_scenario_questions(chapter, text)
        for q in sc_questions:
            qid = insert_question(q)
            if qid:
                total_ins += 1
        total_gen += len(sc_questions)
        print(f"  [情境] {chapter}: +{len(sc_questions)}")

        # 多選題
        mc_questions = generate_multichoice_questions(chapter, text)
        for q in mc_questions:
            qid = insert_question(q)
            if qid:
                total_ins += 1
        total_gen += len(mc_questions)
        print(f"  [多選] {chapter}: +{len(mc_questions)}")

        time.sleep(2)  # rate limit

    # === Task 5: 平衡 T/F 比例 ===
    print("\n--- Task 5: 平衡 T/F（補 F 題）---")
    tf_bias_chapters = {
        "L212 節能技術應用與能源管理": 15,  # 64.6% T → 需加約 15 題 F
        "模擬題與計算練習": 8,               # 62.1% T → 需加約 8 題 F
        "L221 碳管理法規與國際倡議": 5,      # 56.4% T
        "L213 再生能源與綠電導入": 5,        # 54.9% T
    }

    for chapter, num_f in tf_bias_chapters.items():
        text = load_chapter_text(chapter)
        if not text:
            continue

        f_questions = generate_false_tf(chapter, text, num=num_f)
        for q in f_questions:
            qid = insert_question(q)
            if qid:
                total_ins += 1
        total_gen += len(f_questions)
        print(f"  [F題] {chapter}: +{len(f_questions)}")
        time.sleep(2)

    # === Task 8: L211 補強 ===
    print("\n--- Task 8: L211 補強 ---")
    l211_text = load_chapter_text("L211 組織節能減碳策略", max_chars=10000)
    if l211_text:
        # 跑 3 輪，每輪 5 choice + 5 tf
        for round_num in range(3):
            # 用不同的 text 段落避免重複
            offset = round_num * 3000
            text_slice = l211_text[offset:offset + 5000]
            if len(text_slice) < 500:
                text_slice = l211_text[:5000]

            questions = generate_l211_boost(text_slice, num_choice=5, num_tf=5)
            for q in questions:
                qid = insert_question(q)
                if qid:
                    total_ins += 1
            total_gen += len(questions)
            print(f"  [L211 round {round_num + 1}] +{len(questions)}")
            time.sleep(3)

    # === 總結 ===
    print(f"\n{'=' * 60}")
    print(f"增強完成！")
    print(f"  總生成: {total_gen}")
    print(f"  總插入: {total_ins}")

    # 驗證
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT type, COUNT(*) FROM questions GROUP BY type ORDER BY type"
    ).fetchall()
    print(f"\n  題型分布:")
    for t, cnt in rows:
        print(f"    {t}: {cnt}")

    rows = conn.execute(
        "SELECT answer, COUNT(*) FROM questions WHERE type='truefalse' GROUP BY answer"
    ).fetchall()
    print(f"\n  是非題 T/F:")
    for ans, cnt in rows:
        print(f"    {ans}: {cnt}")

    rows = conn.execute(
        "SELECT chapter_group, COUNT(*) FROM questions GROUP BY chapter_group ORDER BY COUNT(*) DESC"
    ).fetchall()
    print(f"\n  章節分布:")
    for ch, cnt in rows:
        print(f"    {ch}: {cnt}")

    conn.close()


if __name__ == "__main__":
    main()
