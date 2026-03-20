"""
批次擴充弱勢章節題庫：
- 建築與公共工程: +20 choice, +15 truefalse, +4 scenario_choice, +3 multichoice
- 產業節能案例:   +15 choice, +10 truefalse, +4 scenario_choice, +3 multichoice

使用 text 檔案 + Gemini 2.5 Flash 生成題目。
"""

import json
import os
import random
import re
import sqlite3
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-2.5-flash"
DB_PATH = "data/questions.db"
TEXTS_DIR = Path("data/texts")

# === 章節 → text 檔案對應 ===
CHAPTER_TEXTS = {
    "建築與公共工程": [
        "公有建築工程全生命週期節能減碳作業指引(內政部 114年 6月 12日台內建研字第 1147638396號函發布)_879d87.txt",
        "建築物節約能源設計技術規範_ad76cc.txt",
        "國內外低碳建築推動措施評析_495f37.txt",
        "公共工程節能減碳檢核注意事項1110831逐點說明_d450aa.txt",
        "國內外既有建築物改善⾄近零碳之技術發展研究(內政部建築研究所委託研究報告 中華民國 113 年 12 月)_229037.txt",
        "政府機關及學校用電效率提升計畫_931ea6.txt",
        "政府機關辦公室節能技術手冊(經濟部能源局 編印)_5db7e8.txt",
        "校園降溫及校舍節能策略檢核表_83c61b.txt",
        "行政院公共工程委員會主管法規共用系統-法規內容-公共工程節能減碳檢核注意事項_861bf1.txt",
        "附件公共工程節能減碳檢核表_04d394.txt",
        "集合住宅節能技術手冊(經濟部能源局 編印)_09a529.txt",
        "分析及檢討-經濟部與內政部節能政策_bc6515.txt",
    ],
    "產業節能案例": [
        "造紙產業減碳技術案例彙編(114年)_94bcc4.txt",
        "造紙產業減碳技術案例彙編(114年)_bb9179.txt",
        "紡織業低碳生產技術彙編(113年)_25795c.txt",
        "紡織業低碳生產技術彙編(113年)_7ec6ad.txt",
        "石化業低碳生產技術彙編(112年)_630001.txt",
        "石化業低碳生產技術彙編(112年)_99501f.txt",
        "淨零碳排放趨勢下的未來鋼鐵業20241016-黃啟峰_294ccd.txt",
        "低碳生產技術彙編-製程冷卻系統節能技術應用篇(110年)_44d981.txt",
        "低碳生產技術彙編-製程動力系統節能技術應用篇(111年)_bbc053.txt",
        "低碳生產技術彙編-製程餘熱回收技術應用篇(110年)_731e28.txt",
        "工廠廢熱回收潛力與節能技術案例分析-2_6cda8b.txt",
        "產業照明系統節能技術手冊(109年版)-4_d4a707.txt",
    ],
}

# === 生成目標 ===
GENERATION_TARGETS = {
    "建築與公共工程": {
        "choice": 20,
        "truefalse": 15,
        "scenario_choice": 4,
        "multichoice": 3,
    },
    "產業節能案例": {
        "choice": 15,
        "truefalse": 10,
        "scenario_choice": 4,
        "multichoice": 3,
    },
}


def load_chapter_text(chapter: str, max_chars: int = 12000) -> str:
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


def load_chapter_text_slice(chapter: str, offset: int, max_chars: int = 8000) -> str:
    """載入章節 text 的不同段落，用於避免重複"""
    files = CHAPTER_TEXTS.get(chapter, [])
    combined = ""
    for fname in files:
        path = TEXTS_DIR / fname
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="ignore")
            combined += content + "\n\n"
    if offset >= len(combined):
        offset = 0
    return combined[offset : offset + max_chars]


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
                print(f"    Error: {err[:200]}")
                return ""
    return ""


def parse_json_array(text: str) -> list[dict]:
    """從 Gemini 回傳文字中提取 JSON 陣列"""
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
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
                q.get("source_file", "batch_expand_weak_chapters.py"),
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


def validate_explanation(explanation: str) -> bool:
    """驗證解析長度 >= 80 字元"""
    return len(explanation or "") >= 80


# ============================================================
# Prompt builders
# ============================================================

ANSWER_POSITIONS = ["A", "B", "C", "D"]


def build_choice_prompt(chapter: str, text: str, num: int, batch_idx: int) -> str:
    """產生選擇題的 prompt，要求答案位置均勻分布"""
    # 預先分配每題的正確答案位置
    positions = []
    for i in range(num):
        positions.append(ANSWER_POSITIONS[(i + batch_idx * 3) % 4])
    position_hint = "、".join(
        [f"第{i+1}題={p}" for i, p in enumerate(positions)]
    )

    return f"""你是 iPAS 淨零碳規劃師中級考試的出題專家。
請根據以下教材重點，產生 {num} 題「選擇題」。

教材重點（章節：{chapter}）：
---
{text}
---

規則：
1. 每題有 A/B/C/D 四個選項，只有一個正確答案
2. 正確答案的位置分配如下：{position_hint}
3. 混合難度 1/2/3（1=基礎記憶, 2=理解應用, 3=分析計算）
4. 解析必須 ≥ 80 字，說明正確選項理由並提及至少一個干擾選項為何錯
5. 題目要涵蓋不同知識點，不要重複相同概念
6. 選項內容要有合理性和區辨度

JSON 格式（直接輸出 JSON，不要其他文字）：
[
  {{
    "type": "choice",
    "content": "題目？",
    "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...",
    "answer": "A",
    "difficulty": 1,
    "explanation": "解析（≥80字）..."
  }}
]"""


def build_truefalse_prompt(
    chapter: str, text: str, num_true: int, num_false: int
) -> str:
    """產生是非題的 prompt，確保 T/F 比例平衡"""
    return f"""你是 iPAS 淨零碳規劃師中級考試的出題專家。
請根據以下教材重點，產生 {num_true + num_false} 題「是非題」。

教材重點（章節：{chapter}）：
---
{text}
---

規則：
1. 其中 {num_true} 題答案為 T（正確），{num_false} 題答案為 F（錯誤）
2. F 題要設計成看起來合理但實際有錯誤的敘述（常見陷阱：數字錯誤、概念混淆、因果倒置、範圍錯誤）
3. T 題要是教材中明確提到的重要事實
4. 混合難度 1/2/3
5. 解析必須 ≥ 80 字，說明該敘述為何正確或錯誤
6. 題目要涵蓋不同知識點

JSON 格式（直接輸出 JSON，不要其他文字）：
[
  {{
    "type": "truefalse",
    "content": "敘述...",
    "answer": "T",
    "difficulty": 2,
    "explanation": "解析（≥80字）..."
  }}
]"""


def build_scenario_prompt(chapter: str, text: str, num_groups: int) -> str:
    """產生情境題的 prompt"""
    return f"""你是 iPAS 淨零碳規劃師中級考試的出題專家。
請根據以下教材重點，產生 {num_groups} 組「情境題組」。

教材重點（章節：{chapter}）：
---
{text}
---

情境題規則：
- 先描述一個具體的台灣企業/機構情境（120-200 字），包含具體背景、數據、面臨的問題
- 每組 2 題子題（單選）
- 第一題考基本判斷（難度 1-2），第二題考分析或計算（難度 2-3）
- 正確答案位置要隨機分布在 A/B/C/D，不要全部放 B
- 解析必須 ≥ 80 字，引用具體法規、數據或技術原理

JSON 格式（直接輸出 JSON，不要其他文字）：
[
  {{
    "scenario_text": "某企業/機構情境描述...",
    "questions": [
      {{
        "type": "scenario_choice",
        "content": "根據上述情境，...？",
        "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...",
        "answer": "A",
        "difficulty": 1,
        "explanation": "解析（≥80字）..."
      }},
      {{
        "type": "scenario_choice",
        "content": "...？",
        "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...",
        "answer": "D",
        "difficulty": 3,
        "explanation": "解析（≥80字）..."
      }}
    ]
  }}
]"""


def build_multichoice_prompt(chapter: str, text: str, num: int) -> str:
    """產生複選題的 prompt"""
    return f"""你是 iPAS 淨零碳規劃師中級考試的出題專家。
請根據以下教材重點，產生 {num} 題「複選題」。

教材重點（章節：{chapter}）：
---
{text}
---

複選題規則：
- 每題有 A/B/C/D 四個選項
- 正確答案為 2-3 個選項（不能只有 1 個，也不能全選）
- 題目要明確寫「下列哪些敘述正確？（複選）」
- 干擾選項要有合理性
- 混合難度 2/3
- 解析必須 ≥ 80 字，逐一說明各選項正確或錯誤的原因

JSON 格式（直接輸出 JSON，不要其他文字）：
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


# ============================================================
# Generation + validation
# ============================================================


def generate_choice_questions(
    chapter: str, text: str, num: int, batch_idx: int = 0
) -> list[dict]:
    """生成選擇題並驗證"""
    prompt = build_choice_prompt(chapter, text, num, batch_idx)
    raw = call_gemini(prompt, max_tokens=12000)
    questions = parse_json_array(raw)

    results = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        q["type"] = "choice"
        if q.get("answer") not in ANSWER_POSITIONS:
            continue
        if not all(q.get(f"option_{k}") for k in "abcd"):
            continue
        if q.get("difficulty") not in (1, 2, 3):
            q["difficulty"] = 2
        if not validate_explanation(q.get("explanation")):
            continue
        q["chapter_group"] = chapter
        q["chapter"] = chapter
        q["source_file"] = "batch_expand_weak_chapters.py"
        results.append(q)
    return results


def generate_truefalse_questions(
    chapter: str, text: str, num_true: int, num_false: int
) -> list[dict]:
    """生成是非題並驗證 T/F 比例"""
    prompt = build_truefalse_prompt(chapter, text, num_true, num_false)
    raw = call_gemini(prompt, max_tokens=10000)
    questions = parse_json_array(raw)

    results = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        q["type"] = "truefalse"
        if q.get("answer") not in ("T", "F"):
            continue
        if q.get("difficulty") not in (1, 2, 3):
            q["difficulty"] = 2
        if not validate_explanation(q.get("explanation")):
            continue
        q["chapter_group"] = chapter
        q["chapter"] = chapter
        q["source_file"] = "batch_expand_weak_chapters.py"
        results.append(q)
    return results


def generate_scenario_questions(
    chapter: str, text: str, num_groups: int
) -> list[dict]:
    """生成情境題並驗證"""
    prompt = build_scenario_prompt(chapter, text, num_groups)
    raw = call_gemini(prompt, max_tokens=12000)
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
            if sq.get("answer") not in ANSWER_POSITIONS:
                continue
            if not all(sq.get(f"option_{k}") for k in "abcd"):
                continue
            if sq.get("difficulty") not in (1, 2, 3):
                sq["difficulty"] = 2
            if not validate_explanation(sq.get("explanation")):
                continue
            sq["scenario_id"] = scenario_id
            sq["scenario_text"] = scenario_text
            sq["chapter_group"] = chapter
            sq["chapter"] = chapter
            sq["source_file"] = "batch_expand_weak_chapters.py"
            results.append(sq)
    return results


def generate_multichoice_questions(
    chapter: str, text: str, num: int
) -> list[dict]:
    """生成複選題並驗證"""
    prompt = build_multichoice_prompt(chapter, text, num)
    raw = call_gemini(prompt, max_tokens=8000)
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
        if q.get("difficulty") not in (1, 2, 3):
            q["difficulty"] = 2
        if not validate_explanation(q.get("explanation")):
            continue
        q["chapter_group"] = chapter
        q["chapter"] = chapter
        q["source_file"] = "batch_expand_weak_chapters.py"
        results.append(q)
    return results


# ============================================================
# Main
# ============================================================


def run_chapter(chapter: str, targets: dict) -> dict:
    """對單一章節執行所有題型的生成"""
    stats = {"generated": 0, "inserted": 0}

    print(f"\n{'='*50}")
    print(f"章節: {chapter}")
    print(f"目標: {targets}")
    print(f"{'='*50}")

    # --- 選擇題 (分批生成以避免重複) ---
    total_choice = targets.get("choice", 0)
    if total_choice > 0:
        choice_collected = []
        batch_size = 10
        batch_idx = 0
        while len(choice_collected) < total_choice and batch_idx < 5:
            needed = min(batch_size, total_choice - len(choice_collected))
            text_offset = batch_idx * 4000
            text = load_chapter_text_slice(chapter, text_offset, max_chars=8000)
            if not text:
                break

            print(f"  [選擇題 batch {batch_idx+1}] 請求 {needed} 題...")
            questions = generate_choice_questions(
                chapter, text, needed, batch_idx
            )
            choice_collected.extend(questions)
            print(f"    取得 {len(questions)} 題 (累計 {len(choice_collected)})")
            batch_idx += 1
            time.sleep(3)

        for q in choice_collected[:total_choice]:
            qid = insert_question(q)
            if qid:
                stats["inserted"] += 1
        stats["generated"] += len(choice_collected[:total_choice])
        print(f"  [選擇題] 插入 {min(len(choice_collected), total_choice)} 題")

    # --- 是非題 (50:50 T/F) ---
    total_tf = targets.get("truefalse", 0)
    if total_tf > 0:
        num_true = total_tf // 2
        num_false = total_tf - num_true
        # 分 2 批
        tf_collected = []
        for tf_batch in range(2):
            nt = num_true // 2 if tf_batch == 0 else num_true - num_true // 2
            nf = num_false // 2 if tf_batch == 0 else num_false - num_false // 2
            if nt + nf == 0:
                continue
            text_offset = tf_batch * 5000
            text = load_chapter_text_slice(chapter, text_offset, max_chars=8000)
            if not text:
                break

            print(f"  [是非題 batch {tf_batch+1}] 請求 T={nt}, F={nf}...")
            questions = generate_truefalse_questions(chapter, text, nt, nf)
            tf_collected.extend(questions)
            print(f"    取得 {len(questions)} 題 (累計 {len(tf_collected)})")
            time.sleep(3)

        for q in tf_collected[:total_tf]:
            qid = insert_question(q)
            if qid:
                stats["inserted"] += 1
        stats["generated"] += len(tf_collected[:total_tf])

        # 統計 T/F 分布
        t_count = sum(1 for q in tf_collected[:total_tf] if q.get("answer") == "T")
        f_count = sum(1 for q in tf_collected[:total_tf] if q.get("answer") == "F")
        print(f"  [是非題] 插入 {min(len(tf_collected), total_tf)} 題 (T={t_count}, F={f_count})")

    # --- 情境題 ---
    total_sc = targets.get("scenario_choice", 0)
    if total_sc > 0:
        num_groups = (total_sc + 1) // 2  # 每組 2 題
        text = load_chapter_text(chapter, max_chars=8000)
        if text:
            print(f"  [情境題] 請求 {num_groups} 組...")
            questions = generate_scenario_questions(chapter, text, num_groups)
            for q in questions[:total_sc]:
                qid = insert_question(q)
                if qid:
                    stats["inserted"] += 1
            stats["generated"] += len(questions[:total_sc])
            print(f"  [情境題] 插入 {min(len(questions), total_sc)} 題")
        time.sleep(3)

    # --- 複選題 ---
    total_mc = targets.get("multichoice", 0)
    if total_mc > 0:
        text = load_chapter_text_slice(chapter, 3000, max_chars=8000)
        if text:
            print(f"  [複選題] 請求 {total_mc} 題...")
            questions = generate_multichoice_questions(chapter, text, total_mc)
            for q in questions[:total_mc]:
                qid = insert_question(q)
                if qid:
                    stats["inserted"] += 1
            stats["generated"] += len(questions[:total_mc])
            print(f"  [複選題] 插入 {min(len(questions), total_mc)} 題")
        time.sleep(3)

    return stats


def verify_results():
    """驗證生成結果"""
    conn = sqlite3.connect(DB_PATH)

    print(f"\n{'='*60}")
    print("驗證結果")
    print(f"{'='*60}")

    # 目標章節統計
    for chapter in GENERATION_TARGETS:
        rows = conn.execute(
            "SELECT type, COUNT(*) FROM questions WHERE chapter_group = ? GROUP BY type ORDER BY type",
            (chapter,),
        ).fetchall()
        print(f"\n  {chapter}:")
        total = 0
        for t, cnt in rows:
            print(f"    {t}: {cnt}")
            total += cnt
        print(f"    合計: {total}")

        # T/F 比例
        tf_rows = conn.execute(
            "SELECT answer, COUNT(*) FROM questions WHERE chapter_group = ? AND type = 'truefalse' GROUP BY answer",
            (chapter,),
        ).fetchall()
        if tf_rows:
            print(f"    是非題 T/F 分布: {dict(tf_rows)}")

        # 選擇題答案分布
        ch_rows = conn.execute(
            "SELECT answer, COUNT(*) FROM questions WHERE chapter_group = ? AND type = 'choice' GROUP BY answer",
            (chapter,),
        ).fetchall()
        if ch_rows:
            print(f"    選擇題答案分布: {dict(ch_rows)}")

    # 解析長度檢查
    short_expl = conn.execute(
        """SELECT COUNT(*) FROM questions
           WHERE chapter_group IN ('建築與公共工程', '產業節能案例')
             AND source_file = 'batch_expand_weak_chapters.py'
             AND LENGTH(explanation) < 80""",
    ).fetchone()[0]
    print(f"\n  新增題目中解析 < 80 字元: {short_expl}")

    # 總體統計
    total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    print(f"\n  題庫總題數: {total}")

    conn.close()


def main():
    print("=" * 60)
    print("iPAS 題庫擴充 — 弱勢章節補強")
    print("=" * 60)

    total_stats = {"generated": 0, "inserted": 0}

    for chapter, targets in GENERATION_TARGETS.items():
        chapter_stats = run_chapter(chapter, targets)
        total_stats["generated"] += chapter_stats["generated"]
        total_stats["inserted"] += chapter_stats["inserted"]

    print(f"\n{'='*60}")
    print("生成完成！")
    print(f"  總生成: {total_stats['generated']}")
    print(f"  總插入: {total_stats['inserted']}")

    verify_results()


if __name__ == "__main__":
    main()
