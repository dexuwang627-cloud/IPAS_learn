"""
第三輪（兩步法）：
  Step 1: 每批頁面 → Gemini 摘要重點（文字）
  Step 2: 重點文字 → 出題（純文字，不傳圖片）
好處：避免大圖斷線，題目更聚焦，多樣性更高。
"""
import json
import gc
import os
import sys
import time
import tempfile
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types
from pdf2image import convert_from_path

from database import init_db, migrate_add_explanation
from services.embedding_service import init_chroma
from services.drive_generator import download_pdf, get_pdf_page_count
from services.question_generator import _parse_response, insert_question_with_dedup

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-2.5-flash"
DB_PATH = "data/questions.db"

PAGES_PER_BATCH = 10
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
- 不要省略細節，寧可多列不要少列

範例：
- 範疇一（Scope 1）：直接排放，來自組織擁有或控制的排放源
- ISO 14064-1 將溫室氣體分為七大類：CO2、CH4、N2O、HFCs、PFCs、SF6、NF3
- GWP（全球暖化潛勢）：CH4 = 28, N2O = 265（以 100 年為基準）
"""

QUESTION_PROMPT = """你是一位 iPAS 產業人才能力鑑定的出題專家。

以下是教材的重點摘要，請根據這些知識點出題。

教材重點：
{summary}

請產生 {num_choice} 題選擇題和 {num_tf} 題是非題。
難度要求：{diff_label}

請嚴格遵守以下 JSON 格式輸出，不要輸出任何其他文字：

[
  {{
    "type": "choice",
    "content": "題目內容",
    "option_a": "選項A",
    "option_b": "選項B",
    "option_c": "選項C",
    "option_d": "選項D",
    "answer": "A",
    "difficulty": {difficulty},
    "explanation": "說明正確答案的理由，並簡述干擾選項為何錯誤"
  }},
  {{
    "type": "truefalse",
    "content": "題目內容",
    "answer": "T",
    "difficulty": {difficulty},
    "explanation": "說明該敘述為何正確或錯誤，引用具體內容"
  }}
]

規則：
1. 選擇題 answer 只能是 A/B/C/D，正確答案均勻分布
2. 是非題 answer 只能是 T/F，各佔約一半
3. 題目必須基於摘要中的具體知識點（數據、名詞、流程）
4. 干擾選項要有合理性，不能一眼看出錯誤
5. explanation 引用具體內容，1-3 句話
"""


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
    """Step 1: 圖片 → 文字摘要"""
    parts = []
    for p in image_paths:
        parts.append(types.Part.from_bytes(
            data=p.read_bytes(), mime_type="image/jpeg",
        ))
    parts.append(SUMMARY_PROMPT)

    response = _client.models.generate_content(
        model=MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=4096,
        ),
    )
    return response.text


def step2_generate(summary, num_choice, num_tf, difficulty):
    """Step 2: 文字摘要 → 出題"""
    labels = {
        1: "簡單（定義、名詞解釋）",
        2: "中等（比較、應用、流程）",
        3: "困難（計算、情境分析、整合判斷）",
    }
    prompt = QUESTION_PROMPT.format(
        summary=summary,
        num_choice=num_choice,
        num_tf=num_tf,
        difficulty=difficulty,
        diff_label=labels[difficulty],
    )

    response = _client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.9,
            max_output_tokens=4096,
        ),
    )
    return _parse_response(response.text)


def _call_with_retry(fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err or "503" in err:
            time.sleep(20)
            return fn(*args)
        raise


def process_batch(pdf_path, start, end, tmpdir, file_name,
                  difficulty, num_choice, num_tf):
    """兩步法處理一個批次"""
    img_dir = os.path.join(tmpdir, f"d{difficulty}_p{start}")
    os.makedirs(img_dir, exist_ok=True)

    # Step 1: 圖片 → 摘要
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
        print(f"    p.{start}-{end} summary too short, skip")
        return []

    # Step 2: 摘要 → 出題
    try:
        questions = _call_with_retry(
            step2_generate, summary, num_choice, num_tf, difficulty,
        )
    except Exception as e:
        print(f"    p.{start}-{end} d{difficulty} gen error: {str(e)[:80]}")
        return []

    chapter = file_name.replace(".pdf", "")
    for q in questions:
        q["chapter"] = chapter
        q["source_file"] = f"{file_name} (p.{start}-{end},d{difficulty},r3)"

    return questions


def process_one_pdf(file_id, file_name):
    print(f"\n{'='*60}")
    print(f"R3: {file_name}")
    print(f"{'='*60}")

    results = {"generated": 0, "inserted": 0, "duplicates": 0}

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "source.pdf")
        print(f"  Downloading...")
        download_pdf(file_id, pdf_path)

        total_pages = min(get_pdf_page_count(pdf_path), MAX_PAGES)
        print(f"  {total_pages} pages")

        rounds = [
            {"difficulty": 1, "num_choice": 3, "num_tf": 1},
            {"difficulty": 2, "num_choice": 4, "num_tf": 2},
            {"difficulty": 3, "num_choice": 4, "num_tf": 2},
        ]

        batches = []
        for start in range(1, total_pages + 1, PAGES_PER_BATCH):
            end = min(start + PAGES_PER_BATCH - 1, total_pages)
            batches.append((start, end))

        total_tasks = len(batches) * len(rounds)
        print(f"  {len(batches)} batches x 3 diff = {total_tasks} tasks")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for start, end in batches:
                for rcfg in rounds:
                    future = executor.submit(
                        process_batch, pdf_path, start, end, tmpdir,
                        file_name, rcfg["difficulty"],
                        rcfg["num_choice"], rcfg["num_tf"],
                    )
                    futures[future] = (start, end, rcfg["difficulty"])

            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                questions = future.result()
                inserted = 0
                duped = 0
                for q in questions:
                    result = insert_question_with_dedup(q)
                    if result["inserted"]:
                        inserted += 1
                    else:
                        duped += 1
                results["generated"] += len(questions)
                results["inserted"] += inserted
                results["duplicates"] += duped

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
    init_chroma()

    name_to_id = load_drive_files()

    total_gen = 0
    total_ins = 0
    total_dup = 0

    print(f"Round 3 (two-step): {len(CORE_TEXTBOOKS)} core textbooks")
    print(f"Strategy: images → summary → questions")
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
    print(f"Round 3 complete!")
    print(f"  Generated: {total_gen}")
    print(f"  Inserted:  {total_ins}")
    print(f"  Duplicates: {total_dup}")

    conn = sqlite3.connect(DB_PATH)
    total_q = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    print(f"  Total questions: {total_q}")


if __name__ == "__main__":
    main()
