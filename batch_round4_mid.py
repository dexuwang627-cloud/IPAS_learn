"""
第四輪：中型 PDF (50-150MB) 兩步法出題 + 三角度。
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

PAGES_PER_BATCH = 12
DPI = 100
JPEG_QUALITY = 60
MAX_PAGES = 200
MAX_WORKERS = 8

SUMMARY_PROMPT = """請仔細閱讀以上教材頁面，擷取所有重要知識點。

輸出格式（純文字條列）：
- 每個知識點一行
- 包含：專有名詞定義、數據數字、公式、流程步驟、法規條文、比較差異、案例
- 盡量保留原文的精確用詞和數據
- 不要省略細節
"""

ANGLE_PROMPTS = {
    "general": {
        "label": "通用題",
        "prompt": """你是 iPAS 出題專家。根據以下教材重點出題。

教材重點：
{summary}

請產生 {num_choice} 題選擇題和 {num_tf} 題是非題。混合簡單、中等、困難三種難度。

JSON 格式：
[
  {{"type": "choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "A", "difficulty": 2, "explanation": "..."}},
  {{"type": "truefalse", "content": "...", "answer": "T", "difficulty": 1, "explanation": "..."}}
]

規則：選擇題答案均勻分布 A/B/C/D，是非題 T/F 各半。直接輸出 JSON。""",
    },
    "calculation": {
        "label": "計算與數據題",
        "prompt": """你是 iPAS 出題專家。根據以下教材重點，專出計算題和數據記憶題。

教材重點：
{summary}

要求：涉及具體數字、百分比、換算公式、排放係數等。

請產生 {num_choice} 題選擇題和 {num_tf} 題是非題。

JSON 格式：
[
  {{"type": "choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "A", "difficulty": 3, "explanation": "..."}},
  {{"type": "truefalse", "content": "...", "answer": "T", "difficulty": 2, "explanation": "..."}}
]

規則：選擇題答案均勻分布 A/B/C/D，是非題 T/F 各半。直接輸出 JSON。""",
    },
    "scenario": {
        "label": "情境案例題",
        "prompt": """你是 iPAS 出題專家。根據以下教材重點，專出情境案例分析題。

教材重點：
{summary}

要求：每題先描述企業情境，再問應如何操作或歸類。

請產生 {num_choice} 題選擇題和 {num_tf} 題是非題。

JSON 格式：
[
  {{"type": "choice", "content": "...", "option_a": "...", "option_b": "...", "option_c": "...", "option_d": "...", "answer": "A", "difficulty": 3, "explanation": "..."}},
  {{"type": "truefalse", "content": "...", "answer": "T", "difficulty": 2, "explanation": "..."}}
]

規則：選擇題答案均勻分布 A/B/C/D，是非題 T/F 各半。直接輸出 JSON。""",
    },
}


def load_mid_pdfs():
    with open("data/drive_files.json") as f:
        all_files = json.load(f)
    mid = [
        f for f in all_files
        if 50 <= f.get("size_mb", 0) <= 150
        and f["name"].endswith(".pdf")
        and "google_type" not in f
    ]
    return sorted(mid, key=lambda x: x["size_mb"])


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
        model=MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            temperature=0.3, max_output_tokens=4096,
        ),
    )
    return response.text


def step2_generate(summary, angle_key, num_choice, num_tf):
    prompt = ANGLE_PROMPTS[angle_key]["prompt"].format(
        summary=summary, num_choice=num_choice, num_tf=num_tf,
    )
    response = _client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.95, max_output_tokens=4096,
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


def process_batch(pdf_path, start, end, tmpdir, file_name, angle_key):
    img_dir = os.path.join(tmpdir, f"{angle_key}_p{start}")
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

    num_choice = 4 if angle_key == "general" else 3
    num_tf = 2

    try:
        questions = _call_with_retry(
            step2_generate, summary, angle_key, num_choice, num_tf,
        )
    except Exception as e:
        print(f"    p.{start}-{end} {angle_key} error: {str(e)[:80]}")
        return []

    chapter = file_name.replace(".pdf", "")
    for q in questions:
        q["chapter"] = chapter
        q["source_file"] = f"{file_name} (p.{start}-{end},{angle_key},r4)"

    return questions


def process_one_pdf(file_id, file_name):
    print(f"\n{'='*60}")
    print(f"R4: {file_name}")
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

        angles = list(ANGLE_PROMPTS.keys())
        total_tasks = len(batches) * len(angles)
        print(f"  {len(batches)} batches x {len(angles)} angles = {total_tasks} tasks")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for start, end in batches:
                for angle_key in angles:
                    future = executor.submit(
                        process_batch, pdf_path, start, end, tmpdir,
                        file_name, angle_key,
                    )
                    futures[future] = (start, end, angle_key)

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
    init_chroma()

    pdfs = load_mid_pdfs()
    total_gen = 0
    total_ins = 0
    total_dup = 0

    print(f"Round 4: {len(pdfs)} mid-size PDFs (50-150MB)")
    print(f"Angles: {', '.join(a['label'] for a in ANGLE_PROMPTS.values())}\n")

    for i, pdf in enumerate(pdfs):
        file_id = pdf.get("id")
        if not file_id:
            print(f"[{i+1}/{len(pdfs)}] SKIP: {pdf['name']} (no id)")
            continue

        try:
            result = process_one_pdf(file_id, pdf["name"])
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
    print(f"Round 4 complete!")
    print(f"  Generated: {total_gen}")
    print(f"  Inserted:  {total_ins}")
    print(f"  Duplicates: {total_dup}")

    conn = sqlite3.connect(DB_PATH)
    total_q = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    print(f"  Total questions: {total_q}")


if __name__ == "__main__":
    main()
