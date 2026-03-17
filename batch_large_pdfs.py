"""
處理大型 PDF：一次一個，限制頁數，跑完釋放記憶體。
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

PAGES_PER_BATCH = 20
DPI = 80              # 大 PDF 用更低 DPI 省 RAM
JPEG_QUALITY = 50
MAX_PAGES = 150       # 每個 PDF 最多處理幾頁
MAX_WORKERS = 8

SYSTEM_PROMPT = """你是一位 iPAS 產業人才能力鑑定的出題專家。
請根據教材頁面內容產生高品質考試題目。

請嚴格遵守以下 JSON 格式輸出，不要輸出任何其他文字：

[
  {
    "type": "choice",
    "content": "題目內容",
    "option_a": "選項A",
    "option_b": "選項B",
    "option_c": "選項C",
    "option_d": "選項D",
    "answer": "A",
    "difficulty": 1,
    "explanation": "說明正確答案的理由，並簡述干擾選項為何錯誤"
  },
  {
    "type": "truefalse",
    "content": "題目內容",
    "answer": "T",
    "difficulty": 2,
    "explanation": "說明該敘述為何正確或錯誤，引用教材中的具體內容"
  }
]

規則：
1. 選擇題 answer 只能是 A/B/C/D，正確答案均勻分布
2. 是非題 answer 只能是 T/F，T 和 F 各佔約一半
3. difficulty 只能是 1(簡單)、2(中等)、3(困難)
4. 題目必須基於教材內容，不可憑空捏造
5. 每題必須有明確唯一正確答案
6. explanation 必須基於教材內容，1-3 句話
7. 混合出不同難度的題目
"""

LARGE_PDF_MIN_MB = 150  # 超過此大小視為大型 PDF


def load_large_pdfs() -> list[dict]:
    """從 drive_files.json 動態篩選大型 PDF，依大小排序"""
    with open("data/drive_files.json") as f:
        all_files = json.load(f)
    large = [
        f for f in all_files
        if f.get("size_mb", 0) >= LARGE_PDF_MIN_MB
        and f["name"].endswith(".pdf")
        and "google_type" not in f
    ]
    return sorted(large, key=lambda x: x["size_mb"])


def pdf_to_images(pdf_path: str, first_page: int, last_page: int,
                  output_dir: str) -> list[Path]:
    images = convert_from_path(
        pdf_path, first_page=first_page, last_page=last_page, dpi=DPI,
    )
    paths = []
    for i, img in enumerate(images):
        page_num = first_page + i
        path = Path(output_dir) / f"page_{page_num:03d}.jpg"
        img.save(str(path), "JPEG", quality=JPEG_QUALITY)
        paths.append(path)
    # 釋放 PIL images
    del images
    gc.collect()
    return paths


def generate_from_images(image_paths: list[Path], num_choice: int = 4,
                         num_tf: int = 2) -> list[dict]:
    parts = []
    for p in image_paths:
        parts.append(types.Part.from_bytes(
            data=p.read_bytes(), mime_type="image/jpeg",
        ))

    parts.append(
        f"請根據以上教材頁面內容產生 {num_choice} 題選擇題和 {num_tf} 題是非題。\n"
        f"混合出簡單、中等、困難三種難度。正確答案均勻分布在 A/B/C/D。\n"
        f"請直接輸出 JSON 陣列，不要加其他說明文字。"
    )

    response = _client.models.generate_content(
        model=MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.8,
            max_output_tokens=4096,
        ),
    )
    return _parse_response(response.text)


def _generate_with_retry(image_paths: list[Path]) -> list[dict]:
    """呼叫 Gemini API，遇到限流自動重試一次"""
    try:
        return generate_from_images(image_paths)
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err or "503" in err:
            time.sleep(20)
            return generate_from_images(image_paths)
        raise


def process_batch(pdf_path, start, end, tmpdir, file_name):
    img_dir = os.path.join(tmpdir, f"batch_{start}")
    os.makedirs(img_dir, exist_ok=True)
    image_paths = pdf_to_images(pdf_path, start, end, img_dir)

    try:
        questions = _generate_with_retry(image_paths)
    except Exception as e:
        print(f"    p.{start}-{end} error: {str(e)[:80]}")
        return []

    chapter = file_name.replace(".pdf", "")
    for q in questions:
        q["chapter"] = chapter
        q["source_file"] = f"{file_name} (p.{start}-{end})"

    for p in image_paths:
        p.unlink(missing_ok=True)

    return questions


def process_one_large_pdf(file_id: str, file_name: str, size_mb: float):
    """一次處理一個大 PDF，完成後強制 gc"""
    print(f"\n{'='*60}")
    print(f"Processing: {file_name} ({size_mb:.0f}MB)")
    print(f"{'='*60}")

    results = {"generated": 0, "inserted": 0, "duplicates": 0}

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "source.pdf")
        print(f"  Downloading...")
        download_pdf(file_id, pdf_path)

        total_pages = get_pdf_page_count(pdf_path)
        actual_pages = min(total_pages, MAX_PAGES)
        print(f"  {total_pages} pages total, processing first {actual_pages}")

        batches = []
        for start in range(1, actual_pages + 1, PAGES_PER_BATCH):
            end = min(start + PAGES_PER_BATCH - 1, actual_pages)
            batches.append((start, end))

        print(f"  {len(batches)} batches, {MAX_WORKERS} workers")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for start, end in batches:
                future = executor.submit(
                    process_batch, pdf_path, start, end, tmpdir, file_name,
                )
                futures[future] = (start, end)

            for future in as_completed(futures):
                questions = future.result()
                for q in questions:
                    result = insert_question_with_dedup(q)
                    if result["inserted"]:
                        results["inserted"] += 1
                    else:
                        results["duplicates"] += 1
                results["generated"] += len(questions)

    # 強制 gc
    gc.collect()

    print(f"  Result: +{results['generated']} gen, "
          f"{results['inserted']} new, {results['duplicates']} dup")
    return results


def main():
    init_db()
    migrate_add_explanation()
    init_chroma()

    large_pdfs = load_large_pdfs()

    total_gen = 0
    total_ins = 0
    total_dup = 0

    print(f"Found {len(large_pdfs)} large PDFs (>={LARGE_PDF_MIN_MB}MB)")

    for i, pdf in enumerate(large_pdfs):
        file_id = pdf.get("id")
        if not file_id:
            print(f"[{i+1}/{len(large_pdfs)}] SKIP: {pdf['name']} (no id)")
            continue

        try:
            result = process_one_large_pdf(file_id, pdf["name"], pdf["size_mb"])
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
        time.sleep(3)

    print(f"\n{'='*60}")
    print(f"All large PDFs done!")
    print(f"  Generated: {total_gen}")
    print(f"  Inserted: {total_ins}")
    print(f"  Duplicates: {total_dup}")

    conn = sqlite3.connect(DB_PATH)
    total_q = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    print(f"  Total questions: {total_q}")


if __name__ == "__main__":
    main()
