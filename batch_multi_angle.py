"""
多角度出題 + 密度增強。
每個知識點從 6 個角度出題：定義、比較、應用、計算、陷阱（是非F）、情境。
優先補強題數 < 100 的章節。
"""
import json
import os
import re
import random
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

random.seed(42)

# ============================================================
# 各章節的知識點 + 對應 text 檔案
# ============================================================
CHAPTER_CONFIG = {
    "L211 組織節能減碳策略": {
        "target": 40,  # 新增目標題數
        "texts": [
            "L211_組織節能減碳策略_V1整理.txt",
            "2026 iPAS 淨零中級 科目一 L211 組織節能減碳策略  V1整理 CCChen 20260120_e0d707.txt",
            "ISO 50001能源管理系統輔導與建置_林杏秋 V2_9072bd.txt",
            "20.工廠能源管理建置技術手冊20180628_b14f08.txt",
        ],
        "knowledge_points": [
            "ISO 50001 PDCA 循環：規劃-執行-查核-處置",
            "能源績效指標 EnPI 與能源基準 EnB 的差異與應用",
            "能源管理法：能源大用戶門檻（800kW）、義務、罰則",
            "能源查核申報制度與節能目標（年均節電率 1%）",
            "國家淨零排放路徑 12 項關鍵戰略",
            "碳盤查流程：邊界設定→排放源鑑別→活動數據→排放量計算",
            "邊際減量成本曲線 MACC 與減碳措施優先排序",
            "能源統計指標：能源密集度、電力係數、初級能源",
        ],
    },
    "L221 碳管理法規與國際倡議": {
        "target": 35,
        "texts": [
            "2026淨零中級 L221國內法規的關鍵專有名詞 彙整 CCChen 20260118_fe0fd8.txt",
            "2026淨零中級 L221國際倡議的關鍵專有名詞 彙整  CCChen 20260118_1af66f.txt",
            "iPAS 淨零（中級）L221 國內法規彙整  CCChen  20260117_c2b712.txt",
            "4. CDP 企業問卷和評分方法_2025年_4d0f94.txt",
        ],
        "knowledge_points": [
            "氣候變遷因應法：碳費徵收、碳權交易、免徵額、高碳洩漏產業",
            "IFRS S1/S2 永續揭露準則 vs ISSB",
            "TCFD 四大核心：治理、策略、風險管理、指標與目標",
            "SBTi 科學基礎減量目標：近程/遠程/淨零承諾",
            "CDP 碳揭露問卷：評分機制 A~D-、供應鏈議合",
            "歐盟 CBAM 碳邊境調整機制：過渡期、報告義務",
            "CSRD 企業永續報告指令 vs CSDDD 盡職調查",
        ],
    },
    "L222 碳移除與負碳技術": {
        "target": 35,
        "texts": [
            "L22202-碳移除與負碳技術（如碳匯、CCUS等）_fc083b.txt",
            "L22201-國內外自願減量專案與抵換制度_52e8f3.txt",
            "L22204-內部碳定價與碳資產管理_53e581.txt",
            "L22202-二氧化碳移除 (CDR) 技術綜合評估與前景分析_88d7fb.txt",
        ],
        "knowledge_points": [
            "自然碳匯：綠碳（森林）、藍碳（海洋）、黃碳（土壤）比較",
            "CCUS 技術：捕捉→利用→封存，點源 vs DAC",
            "BECCS 生質能碳捕捉：負排放原理與限制",
            "生物炭固碳：製程、永久性、碳信用認證",
            "國內自願減量專案：申請流程、方法學、額度核發",
            "碳權交易：國內 vs 國外額度、抵換上限（10%）",
            "內部碳定價：影子價格、隱含碳價、內部碳費三種模式",
        ],
    },
    "L223 供應鏈碳管理": {
        "target": 30,
        "texts": [
            "4_Scope3_Calculation_Guidance_價值鏈排放_e5e44b.txt",
            "L22301-GHG Protocol_436ccc.txt",
            "EcoVadis 綜合簡報_346cc0.txt",
            "L22302 供應鏈減碳風險評估與管理機制_CDP_374eb7.txt",
        ],
        "knowledge_points": [
            "GHG Protocol 三個範疇：直接/間接/價值鏈排放",
            "範疇三 15 個類別與計算方法（支出基礎/距離基礎/活動數據）",
            "供應鏈碳管理：熱點分析、供應商議合、減碳路徑",
            "RBA 責任商業聯盟：勞工/健康安全/環境/道德/管理體系",
            "EcoVadis 永續評級：環境/勞工/道德/永續採購四大主題",
            "產品碳足跡 CFP：系統邊界、功能單位、分配法則",
        ],
    },
    "產業節能案例": {
        "target": 25,
        "texts": [
            "造紙產業減碳技術案例彙編(114年)_0b7e09.txt",
            "紡織業低碳生產技術彙編(113年)_57e2c3.txt",
            "石化業低碳生產技術彙編(112年)_7c3b72.txt",
        ],
        "knowledge_points": [
            "造紙業：靴壓技術、廢熱回收、生質燃料替代",
            "紡織業：定型機節能、染色廢水熱回收、智慧能管",
            "石化業：石油腦裂解、製程整合、氫能應用",
            "鋼鐵業：電弧爐 vs 高爐、廢鋼再利用、DRI 直接還原鐵",
            "節能技術投資評估：SPP、NPV、IRR、LCC 實際案例",
        ],
    },
    "L213 再生能源與綠電導入": {
        "target": 25,
        "texts": [
            "L213_再生能源與綠電導入_V1整理.txt",
            "2026 iPAS 淨零中級 科目一 L213  再生能源與綠電導入  V1整理 CCChen 20260120_f74f9a.txt",
        ],
        "knowledge_points": [
            "再生能源憑證 T-REC：申請、交易、與綠電的差異",
            "太陽光電：容量因數、躉購費率 FIT、自用 vs 轉供",
            "風力發電：離岸 vs 陸域、區塊開發、國產化政策",
            "地熱/海洋能：台灣潛力場址、技術挑戰",
            "CPPA 企業購電合約：轉供模式、直供模式、合約要素",
            "儲能系統：鋰電池/液流電池比較、調頻輔助服務",
        ],
    },
}

# ============================================================
# Prompt Templates (6 angles)
# ============================================================

MULTI_ANGLE_PROMPT = """你是 iPAS 淨零碳規劃師中級考試的出題專家。

請針對以下知識點，從 6 個不同角度各出 1 題，共 6 題：

知識點：{knowledge_point}
章節：{chapter}

教材參考：
---
{text_excerpt}
---

6 個角度（每題都不同角度，不可重複）：

1. **定義辨析題**（選擇題，難度 1）
   問某概念的正確定義，干擾選項用易混淆的相似概念

2. **比較分析題**（選擇題，難度 2）
   比較兩個以上相關概念的異同，如「以下關於 X 和 Y 的比較，何者正確？」

3. **實務應用題**（選擇題，難度 2-3）
   給出企業實際情境，問應採取什麼措施或屬於什麼類別

4. **計算/數據題**（選擇題，難度 3）
   需要記住關鍵數字或進行簡單計算（門檻值、比例、費率等）

5. **陷阱辨識題**（是非題，答案為 F，難度 2）
   設計看似正確但有隱含錯誤的敘述（數字錯、因果倒置、範圍錯）

6. **情境應用題**（scenario_choice，難度 2-3）
   具體台灣企業情境 + 1 題子題

嚴格規則：
- 解析必須 ≥ 80 字
- 選擇題解析須說明正確選項理由 + 至少一個干擾選項為何錯
- 正確答案隨機分布在 A/B/C/D
- 使用繁體中文
- 情境題的 scenario_text 要 100-150 字

直接輸出 JSON 陣列（不要 markdown code block）：
[
  {{"type": "choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "C", "difficulty": 1, "explanation": "..."}},
  {{"type": "choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "A", "difficulty": 2, "explanation": "..."}},
  {{"type": "choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "D", "difficulty": 3, "explanation": "..."}},
  {{"type": "choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "B", "difficulty": 3, "explanation": "..."}},
  {{"type": "truefalse", "content": "...", "answer": "F", "difficulty": 2, "explanation": "..."}},
  {{"scenario_text": "...", "questions": [{{"type": "scenario_choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "A", "difficulty": 2, "explanation": "..."}}]}}
]"""


def load_text(files, max_chars=5000):
    combined = ""
    for fname in files:
        path = TEXTS_DIR / fname
        if path.exists():
            combined += path.read_text(encoding="utf-8", errors="ignore") + "\n"
        if len(combined) >= max_chars:
            break
    return combined[:max_chars]


def call_gemini(prompt):
    for attempt in range(3):
        try:
            r = _client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.9, max_output_tokens=12000,
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


def parse_and_validate(raw, chapter):
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        items = json.loads(m.group())
    except json.JSONDecodeError:
        return []

    results = []
    for item in items:
        if not isinstance(item, dict):
            continue

        # Handle scenario wrapper
        if "scenario_text" in item:
            scenario_text = item["scenario_text"]
            scenario_id = str(uuid.uuid4())[:8]
            for sq in item.get("questions", []):
                if not isinstance(sq, dict):
                    continue
                sq["type"] = "scenario_choice"
                if sq.get("answer") not in ("A", "B", "C", "D"):
                    continue
                if not all(sq.get("option_" + k) for k in "abcd"):
                    continue
                sq["scenario_id"] = scenario_id
                sq["scenario_text"] = scenario_text
                sq["chapter_group"] = chapter
                sq["chapter"] = chapter
                if sq.get("difficulty") not in (1, 2, 3):
                    sq["difficulty"] = 2
                results.append(sq)
            continue

        qtype = item.get("type")
        if qtype == "choice":
            if item.get("answer") not in ("A", "B", "C", "D"):
                continue
            if not all(item.get("option_" + k) for k in "abcd"):
                continue
        elif qtype == "truefalse":
            if item.get("answer") not in ("T", "F"):
                continue
        else:
            continue

        if item.get("difficulty") not in (1, 2, 3):
            item["difficulty"] = 2

        item["chapter_group"] = chapter
        item["chapter"] = chapter
        results.append(item)

    return results


def insert_question(q):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO questions
               (chapter, source_file, type, content, option_a, option_b, option_c, option_d,
                answer, difficulty, explanation, scenario_id, scenario_text, chapter_group, bank_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                q.get("chapter", ""),
                "batch_multi_angle.py",
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
        return True
    except Exception:
        return False
    finally:
        conn.close()


def main():
    print("=" * 60)
    print("多角度出題 + 密度增強")
    print("=" * 60)

    total_gen = 0
    total_ins = 0

    for chapter, config in CHAPTER_CONFIG.items():
        target = config["target"]
        text = load_text(config["texts"])
        kps = config["knowledge_points"]

        print(f"\n--- {chapter} (目標 +{target} 題, {len(kps)} 知識點) ---")

        if not text:
            print("  無 text 檔案，跳過")
            continue

        chapter_ins = 0
        for i, kp in enumerate(kps):
            # Use different text segments for variety
            text_offset = (i * 1500) % max(len(text) - 2000, 1)
            text_excerpt = text[text_offset:text_offset + 2500]

            prompt = MULTI_ANGLE_PROMPT.format(
                knowledge_point=kp,
                chapter=chapter,
                text_excerpt=text_excerpt,
            )

            raw = call_gemini(prompt)
            questions = parse_and_validate(raw, chapter)

            for q in questions:
                if insert_question(q):
                    chapter_ins += 1

            total_gen += len(questions)
            print(f"  [{i + 1}/{len(kps)}] {kp[:25]}... → +{len(questions)}")
            time.sleep(2)

            if chapter_ins >= target:
                break

        total_ins += chapter_ins
        print(f"  小計：+{chapter_ins} 題")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"完成！總生成 {total_gen}，總插入 {total_ins}")

    conn = sqlite3.connect(DB_PATH)
    r = conn.execute("SELECT COUNT(*) FROM questions").fetchone()
    print(f"題庫總數：{r[0]}")

    rows = conn.execute(
        """SELECT chapter_group, COUNT(*) FROM questions
           GROUP BY chapter_group ORDER BY COUNT(*) DESC"""
    ).fetchall()
    print("\n章節分布：")
    for ch, cnt in rows:
        print(f"  {ch}: {cnt}")

    # Type distribution
    rows = conn.execute(
        "SELECT type, COUNT(*) FROM questions GROUP BY type ORDER BY COUNT(*) DESC"
    ).fetchall()
    print("\n題型分布：")
    for t, cnt in rows:
        print(f"  {t}: {cnt}")

    conn.close()


if __name__ == "__main__":
    main()
