"""
第二輪加量出題：分難度 + 修正答案分布 + 並行處理。
"""
import json
import os
import re
import sys
import time
import tempfile
import threading
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

PROGRESS_FILE = "data/batch_r2_progress.json"
DRIVE_FILES = "data/drive_files.json"

PAGES_PER_BATCH = 25
DPI = 100
JPEG_QUALITY = 60
MAX_PDF_CONCURRENT = 3
MAX_API_WORKERS = 15

_progress_lock = threading.Lock()
_db_lock = threading.Lock()

# 修正答案分布的 system prompt
SYSTEM_PROMPT_R2 = """你是一位 iPAS 產業人才能力鑑定的出題專家。
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
1. 選擇題 answer 只能是 A/B/C/D
2. 是非題 answer 只能是 T/F
3. difficulty 只能是 1(簡單)、2(中等)、3(困難)
4. 簡單題：定義、基本概念
5. 中等題：比較、應用、流程
6. 困難題：計算、整合分析、情境判斷
7. 題目必須基於教材內容，不可憑空捏造
8. 每題必須有明確唯一正確答案
9. explanation 必須基於教材內容，1-3 句話
10. 選擇題的 explanation 須說明正確選項理由，並提及至少一個干擾選項為何錯
11. 是非題的 explanation 須說明該敘述為何正確或錯誤
12. 重要：正確答案必須均勻分布在 A/B/C/D 四個選項中，不要偏好某個選項
13. 重要：是非題的正確答案 T 和 F 要各佔約一半
"""


def load_progress() -> dict:
    if Path(PROGRESS_FILE).exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": [], "failed": [], "stats": {
        "total_generated": 0, "total_inserted": 0, "total_duplicates": 0,
    }}


def save_progress(progress: dict):
    with _progress_lock:
        with open(PROGRESS_FILE, "w") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)


def load_drive_files() -> list[dict]:
    with open(DRIVE_FILES) as f:
        all_files = json.load(f)
    return [
        f for f in all_files
        if f.get("size_mb", 0) > 0 and "google_type" not in f
    ]


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
    return paths


def generate_from_images_r2(
    image_paths: list[Path],
    num_choice: int,
    num_tf: int,
    difficulty: int,
) -> list[dict]:
    """送圖片給 Gemini，指定難度出題"""
    parts = []
    for p in image_paths:
        parts.append(types.Part.from_bytes(
            data=p.read_bytes(), mime_type="image/jpeg",
        ))

    labels = {1: "簡單（定義、基本概念）", 2: "中等（比較、應用）", 3: "困難（計算、整合分析、情境判斷）"}
    diff_hint = f"\n請只產生難度 {difficulty} 的題目：{labels[difficulty]}"

    parts.append(
        f"請根據以上教材頁面內容產生 {num_choice} 題選擇題和 {num_tf} 題是非題。"
        f"{diff_hint}\n"
        f"正確答案請均勻分布在 A/B/C/D，不要集中在某個選項。\n"
        f"請直接輸出 JSON 陣列，不要加其他說明文字。"
    )

    response = _client.models.generate_content(
        model=MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT_R2,
            temperature=0.8,
            max_output_tokens=4096,
        ),
    )
    return _parse_response(response.text)


def process_single_batch(pdf_path: str, start: int, end: int, tmpdir: str,
                         file_name: str, difficulty: int,
                         num_choice: int, num_tf: int):
    """處理單一頁面批次 + 指定難度"""
    img_dir = os.path.join(tmpdir, f"d{difficulty}_batch_{start}")
    os.makedirs(img_dir, exist_ok=True)
    image_paths = pdf_to_images(pdf_path, start, end, img_dir)

    try:
        questions = generate_from_images_r2(image_paths, num_choice, num_tf, difficulty)
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            time.sleep(30)
            try:
                questions = generate_from_images_r2(image_paths, num_choice, num_tf, difficulty)
            except Exception:
                return []
        elif "503" in err:
            time.sleep(10)
            try:
                questions = generate_from_images_r2(image_paths, num_choice, num_tf, difficulty)
            except Exception:
                return []
        else:
            return []

    chapter = file_name.replace(".pdf", "")
    for q in questions:
        q["chapter"] = chapter
        q["source_file"] = f"{file_name} (p.{start}-{end},d{difficulty},r2)"

    return questions


def process_one_pdf(pdf_info: dict, executor: ThreadPoolExecutor,
                    progress: dict, pdf_index: int, total: int):
    """處理一個 PDF：三個難度各出一輪"""
    file_id = pdf_info["id"]
    file_name = pdf_info["name"]
    size_mb = pdf_info["size_mb"]

    # 大檔用較少頁面
    max_pages = 200 if size_mb > 100 else None

    tag = f"[{pdf_index}/{total}]"
    results = {"generated": 0, "inserted": 0, "duplicates": 0}

    tmpdir = tempfile.mkdtemp()
    try:
        pdf_path = os.path.join(tmpdir, "source.pdf")
        print(f"{tag} Download {file_name} ({size_mb:.1f}MB)...")
        download_pdf(file_id, pdf_path)

        total_pages = get_pdf_page_count(pdf_path)
        if max_pages and total_pages > max_pages:
            total_pages = max_pages

        # 三個難度的出題配置：困難多出一些
        rounds = [
            {"difficulty": 1, "num_choice": 3, "num_tf": 1, "label": "簡單"},
            {"difficulty": 2, "num_choice": 3, "num_tf": 2, "label": "中等"},
            {"difficulty": 3, "num_choice": 4, "num_tf": 2, "label": "困難"},
        ]

        batches_info = []
        for start in range(1, total_pages + 1, PAGES_PER_BATCH):
            end = min(start + PAGES_PER_BATCH - 1, total_pages)
            batches_info.append((start, end))

        print(f"{tag} {file_name}: {total_pages}p, {len(batches_info)} batches x 3 difficulties")

        # 提交所有批次 x 難度到共享 executor
        futures = []
        for start, end in batches_info:
            for rcfg in rounds:
                future = executor.submit(
                    process_single_batch, pdf_path, start, end, tmpdir,
                    file_name, rcfg["difficulty"], rcfg["num_choice"], rcfg["num_tf"],
                )
                futures.append(future)

        for future in as_completed(futures):
            questions = future.result()
            for q in questions:
                with _db_lock:
                    result = insert_question_with_dedup(q)
                if result["inserted"]:
                    results["inserted"] += 1
                else:
                    results["duplicates"] += 1
            results["generated"] += len(questions)

        print(f"{tag} {file_name}: +{results['generated']} gen, "
              f"{results['inserted']} new, {results['duplicates']} dup")

        with _progress_lock:
            progress["completed"].append(file_id)
            progress["stats"]["total_generated"] += results["generated"]
            progress["stats"]["total_inserted"] += results["inserted"]
            progress["stats"]["total_duplicates"] += results["duplicates"]
        save_progress(progress)

    except Exception as e:
        print(f"{tag} {file_name} ERROR: {e}")
        with _progress_lock:
            progress["failed"].append({"id": file_id, "error": str(e)[:200]})
        save_progress(progress)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    init_db()
    migrate_add_explanation()
    init_chroma()

    pdfs = load_drive_files()
    progress = load_progress()
    completed_ids = set(progress["completed"])

    # 第二輪：全部 PDF 重跑（去重會自動擋掉重複題）
    # 但跳過超大檔 >250MB 避免 RAM 爆掉
    pending = [
        p for p in sorted(pdfs, key=lambda x: x["size_mb"])
        if p["id"] not in completed_ids and p["size_mb"] <= 250
    ]

    total = len(pending)
    print(f"\nRound 2: {total} PDFs pending, {len(completed_ids)} done")
    print(f"Concurrency: {MAX_PDF_CONCURRENT} PDFs x {MAX_API_WORKERS} API workers")
    print(f"Each PDF: 3 difficulties (easy/medium/hard), extra hard questions\n")

    with ThreadPoolExecutor(max_workers=MAX_API_WORKERS) as api_executor:
        with ThreadPoolExecutor(max_workers=MAX_PDF_CONCURRENT) as pdf_executor:
            pdf_futures = []
            for i, pdf in enumerate(pending):
                future = pdf_executor.submit(
                    process_one_pdf, pdf, api_executor, progress, i + 1, total,
                )
                pdf_futures.append((future, pdf))

            try:
                for future, pdf in pdf_futures:
                    future.result()
            except KeyboardInterrupt:
                print("\nInterrupted, progress saved.")
                save_progress(progress)
                sys.exit(0)

    save_progress(progress)
    print(f"\nRound 2 done!")
    print(f"  Generated: {progress['stats']['total_generated']}")
    print(f"  Inserted: {progress['stats']['total_inserted']}")
    print(f"  Duplicates: {progress['stats']['total_duplicates']}")

    conn = sqlite3.connect("data/questions.db")
    total_q = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    print(f"\nTotal questions: {total_q}")


if __name__ == "__main__":
    main()
