"""
產生複選題 + 情境題，兩步法。
"""
import json
import gc
import os
import sys
import time
import uuid
import tempfile
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types
from pdf2image import convert_from_path

from database import init_db, migrate_add_explanation, migrate_add_multichoice_scenario
from services.embedding_service import init_chroma
from services.drive_generator import download_pdf, get_pdf_page_count
from services.question_generator import _parse_response, insert_question_with_dedup

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-2.5-flash"
DB_PATH = "data/questions.db"

PAGES_PER_BATCH = 12
DPI = 100
JPEG_QUALITY = 60
MAX_PAGES = 200
MAX_WORKERS = 8

CORE_TEXTBOOKS = [
    "01氣候變遷與溫室氣體管理(上).pdf",
    "02氣候變遷與溫室氣體管理(下).pdf",
    "03溫室氣體盤查作業.pdf",
    "04溫室氣體減量作業與減量額度.pdf",
    "05產品碳足跡.pdf",
]

SUMMARY_PROMPT = """請仔細閱讀以上教材頁面，擷取所有重要知識點。

輸出格式（純文字條列）：
- 每個知識點一行
- 包含：專有名詞定義、數據數字、公式、流程步驟、法規條文、比較差異、案例
- 盡量保留原文的精確用詞和數據
"""

MULTICHOICE_PROMPT = """你是 iPAS 中級考試出題專家。請根據以下教材重點，產生「複選題」。

教材重點：
{summary}

複選題規則：
- 每題有 A/B/C/D 四個選項
- 正確答案為 2-3 個選項（不能只有 1 個，也不能全選）
- 題目要明確寫「下列哪些敘述正確？（複選）」或類似提示
- 干擾選項要有合理性，容易跟正確選項混淆

請產生 {num} 題複選題，混合不同難度。

JSON 格式（直接輸出，不要其他文字）：
[
  {{
    "type": "multichoice",
    "content": "下列關於溫室氣體的敘述，哪些正確？（複選）",
    "option_a": "...",
    "option_b": "...",
    "option_c": "...",
    "option_d": "...",
    "answer": "AC",
    "difficulty": 2,
    "explanation": "A 正確因為...，C 正確因為...。B 錯誤因為...，D 錯誤因為..."
  }}
]"""

SCENARIO_PROMPT = """你是 iPAS 中級考試出題專家。請根據以下教材重點，產生「情境題組」。

教材重點：
{summary}

情境題規則：
- 先描述一個具體的企業情境（100-200 字），包含公司類型、排放數據、面臨的問題
- 針對這個情境出 3 題子題（混合單選和複選）
- 子題之間要有邏輯關聯，由淺到深
- 第一題考基本判斷，第二題考應用，第三題考分析或計算

JSON 格式（直接輸出，不要其他文字）：
[
  {{
    "scenario_text": "某電子製造公司 A，年營收 50 億元，主要產品為印刷電路板...(情境描述)...",
    "questions": [
      {{
        "type": "scenario_choice",
        "content": "根據上述情境，A 公司的用電排放應歸類為哪個範疇？",
        "option_a": "範疇一", "option_b": "範疇二", "option_c": "範疇三", "option_d": "不需計算",
        "answer": "B",
        "difficulty": 1,
        "explanation": "外購電力屬於範疇二間接排放..."
      }},
      {{
        "type": "scenario_multichoice",
        "content": "A 公司若要進行碳盤查，下列哪些步驟是必要的？（複選）",
        "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...",
        "answer": "ABD",
        "difficulty": 2,
        "explanation": "..."
      }},
      {{
        "type": "scenario_choice",
        "content": "若 A 公司年用電量為 2000 萬度，電力排放係數為 0.509 kgCO2e/度...",
        "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...",
        "answer": "C",
        "difficulty": 3,
        "explanation": "..."
      }}
    ]
  }}
]"""


def load_drive_files():
    with open("data/drive_files.json") as f:
        return {f["name"]: f["id"] for f in json.load(f)}


def pdf_to_images(pdf_path, first_page, last_page, output_dir):
    images = convert_from_path(
        pdf_path, first_page=first_page, last_page=last_page, dpi=DPI,
    )
    paths = []
    for i, img in enumerate(images):
        path = Path(output_dir) / f"page_{first_page + i:03d}.jpg"
        img.save(str(path), "JPEG", quality=JPEG_QUALITY)
        paths.append(path)
    del images
    gc.collect()
    return paths


def step1_summarize(image_paths):
    parts = []
    for p in image_paths:
        parts.append(types.Part.from_bytes(
            data=p.read_bytes(), mime_type="image/jpeg",
        ))
    parts.append(SUMMARY_PROMPT)
    response = _client.models.generate_content(
        model=MODEL, contents=parts,
        config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=4096),
    )
    return response.text


def step2_multichoice(summary, num=3):
    prompt = MULTICHOICE_PROMPT.format(summary=summary, num=num)
    response = _client.models.generate_content(
        model=MODEL, contents=prompt,
        config=types.GenerateContentConfig(temperature=0.9, max_output_tokens=4096),
    )
    return _parse_response(response.text)


def step2_scenario(summary):
    prompt = SCENARIO_PROMPT.format(summary=summary)
    response = _client.models.generate_content(
        model=MODEL, contents=prompt,
        config=types.GenerateContentConfig(temperature=0.9, max_output_tokens=8192),
    )
    return _parse_scenario_response(response.text)


def _parse_scenario_response(raw: str) -> list[dict]:
    """解析情境題 JSON，展開為多個 question dict"""
    import re
    json_match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not json_match:
        return []

    try:
        scenarios = json.loads(json_match.group())
    except json.JSONDecodeError:
        return []

    results = []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue

        scenario_text = scenario.get("scenario_text", "")
        if not scenario_text:
            continue

        scenario_id = str(uuid.uuid4())[:8]
        sub_questions = scenario.get("questions", [])

        for sq in sub_questions:
            from services.question_generator import _normalize_question
            normalized = _normalize_question(sq)
            if normalized is None:
                continue

            q_type = normalized["type"]
            ans = normalized["answer"]

            # 驗證
            if q_type in ("scenario_choice",):
                if ans not in ("A", "B", "C", "D"):
                    continue
            elif q_type in ("scenario_multichoice",):
                if not (2 <= len(ans) <= 4 and all(c in "ABCD" for c in ans)):
                    continue
            else:
                continue

            if not all(normalized.get(f"option_{k}") for k in "abcd"):
                continue

            normalized["scenario_id"] = scenario_id
            normalized["scenario_text"] = scenario_text
            results.append(normalized)

    return results


def _call_with_retry(fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err or "503" in err:
            time.sleep(20)
            return fn(*args)
        raise


def process_batch(pdf_path, start, end, tmpdir, file_name, mode):
    """mode: 'multichoice' or 'scenario'"""
    img_dir = os.path.join(tmpdir, f"{mode}_p{start}")
    os.makedirs(img_dir, exist_ok=True)

    image_paths = pdf_to_images(pdf_path, start, end, img_dir)
    try:
        summary = _call_with_retry(step1_summarize, image_paths)
    except Exception as e:
        print(f"    p.{start}-{end} summary error: {str(e)[:80]}")
        return []
    finally:
        for p in image_paths:
            p.unlink(missing_ok=True)

    if not summary or len(summary.strip()) < 50:
        return []

    try:
        if mode == "multichoice":
            questions = _call_with_retry(step2_multichoice, summary, 3)
        else:
            questions = _call_with_retry(step2_scenario, summary)
    except Exception as e:
        print(f"    p.{start}-{end} {mode} error: {str(e)[:80]}")
        return []

    chapter = file_name.replace(".pdf", "")
    for q in questions:
        q["chapter"] = chapter
        q["source_file"] = f"{file_name} (p.{start}-{end},{mode})"

    return questions


def process_one_pdf(file_id, file_name):
    print(f"\n{'='*60}")
    print(f"MC+SC: {file_name}")
    print(f"{'='*60}")

    results = {"generated": 0, "inserted": 0, "duplicates": 0}

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "source.pdf")
        print(f"  Downloading...")
        download_pdf(file_id, pdf_path)

        total_pages = min(get_pdf_page_count(pdf_path), MAX_PAGES)
        print(f"  {total_pages} pages")

        batches = []
        for start in range(1, total_pages + 1, PAGES_PER_BATCH):
            end = min(start + PAGES_PER_BATCH - 1, total_pages)
            batches.append((start, end))

        modes = ["multichoice", "scenario"]
        total_tasks = len(batches) * len(modes)
        print(f"  {len(batches)} batches x {len(modes)} modes = {total_tasks} tasks")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for start, end in batches:
                for mode in modes:
                    future = executor.submit(
                        process_batch, pdf_path, start, end, tmpdir, file_name, mode,
                    )
                    futures[future] = (start, end, mode)

            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                questions = future.result()
                for q in questions:
                    result = insert_question_with_dedup(q)
                    if result["inserted"]:
                        results["inserted"] += 1
                    else:
                        results["duplicates"] += 1
                results["generated"] += len(questions)

                if done_count % 5 == 0:
                    print(f"  [{done_count}/{total_tasks}] "
                          f"+{results['generated']} gen, "
                          f"{results['inserted']} new, "
                          f"{results['duplicates']} dup")

    gc.collect()
    print(f"  Done: +{results['generated']} gen, "
          f"{results['inserted']} new, {results['duplicates']} dup")
    return results


def main():
    init_db()
    migrate_add_explanation()
    migrate_add_multichoice_scenario()
    init_chroma()

    name_to_id = load_drive_files()

    total_gen = 0
    total_ins = 0
    total_dup = 0

    print(f"Multichoice + Scenario: {len(CORE_TEXTBOOKS)} core textbooks")
    print(f"DPI={DPI}, pages/batch={PAGES_PER_BATCH}, workers={MAX_WORKERS}\n")

    for i, name in enumerate(CORE_TEXTBOOKS):
        file_id = name_to_id.get(name)
        if not file_id:
            print(f"[{i+1}/{len(CORE_TEXTBOOKS)}] SKIP: {name}")
            continue

        try:
            result = process_one_pdf(file_id, name)
            total_gen += result["generated"]
            total_ins += result["inserted"]
            total_dup += result["duplicates"]
        except KeyboardInterrupt:
            print("\nInterrupted.")
            sys.exit(0)
        except Exception as e:
            print(f"  FAILED: {e}")
            continue

        print(f"  Cooling down...")
        gc.collect()
        time.sleep(5)

    print(f"\n{'='*60}")
    print(f"Multichoice + Scenario complete!")
    print(f"  Generated: {total_gen}")
    print(f"  Inserted:  {total_ins}")
    print(f"  Duplicates: {total_dup}")

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT type, COUNT(*) FROM questions GROUP BY type ORDER BY type"
    ).fetchall()
    conn.close()
    print(f"\n  By type:")
    for t, cnt in rows:
        print(f"    {t}: {cnt}")


if __name__ == "__main__":
    main()
