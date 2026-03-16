"""
快速批次出題：多 PDF 並行 + 頁面批次並行。
單一 ThreadPoolExecutor 同時處理多份 PDF 的多個頁面批次。
"""
import json
import os
import sys
import time
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from database import init_db, migrate_add_explanation
from services.embedding_service import init_chroma
from services.drive_generator import (
    download_pdf, get_pdf_page_count,
    _generate_from_images,
)
from services.question_generator import insert_question_with_dedup
from pdf2image import convert_from_path

PROGRESS_FILE = "data/batch_progress.json"
DRIVE_FILES = "data/drive_files.json"

# 加速參數
PAGES_PER_BATCH = 25
DPI = 100
JPEG_QUALITY = 60
MAX_PDF_CONCURRENT = 3     # 同時處理幾個 PDF
MAX_API_WORKERS = 15       # API 呼叫總並行數

# Thread-safe 進度鎖
_progress_lock = threading.Lock()
_db_lock = threading.Lock()


def load_progress() -> dict:
    if Path(PROGRESS_FILE).exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": [], "failed": [], "skipped": []}


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


def pdf_to_images_fast(pdf_path: str, first_page: int, last_page: int,
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


def process_single_batch(pdf_path: str, start: int, end: int, tmpdir: str,
                         file_name: str, num_choice: int = 3, num_tf: int = 2):
    """處理單一頁面批次，返回 questions list"""
    img_dir = os.path.join(tmpdir, f"batch_{start}")
    os.makedirs(img_dir, exist_ok=True)
    image_paths = pdf_to_images_fast(pdf_path, start, end, img_dir)

    try:
        questions = _generate_from_images(image_paths, num_choice, num_tf)
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            time.sleep(30)
            try:
                questions = _generate_from_images(image_paths, num_choice, num_tf)
            except Exception:
                return []
        elif "503" in err:
            time.sleep(10)
            try:
                questions = _generate_from_images(image_paths, num_choice, num_tf)
            except Exception:
                return []
        else:
            return []

    chapter = file_name.replace(".pdf", "")
    for q in questions:
        q["chapter"] = chapter
        q["source_file"] = f"{file_name} (p.{start}-{end})"

    return questions


def process_one_pdf(pdf_info: dict, executor: ThreadPoolExecutor,
                    progress: dict, pdf_index: int, total: int):
    """處理一個 PDF：下載 → 提交所有頁面批次到共享 executor → 收集結果"""
    file_id = pdf_info["id"]
    file_name = pdf_info["name"]
    size_mb = pdf_info["size_mb"]

    if size_mb > 300:
        return

    tag = f"[{pdf_index}/{total}]"
    results = {"generated": 0, "inserted": 0, "duplicates": 0}

    tmpdir = tempfile.mkdtemp()
    try:
        pdf_path = os.path.join(tmpdir, "source.pdf")
        print(f"{tag} Download {file_name} ({size_mb:.1f}MB)...")
        download_pdf(file_id, pdf_path)

        total_pages = get_pdf_page_count(pdf_path)
        batches = []
        for start in range(1, total_pages + 1, PAGES_PER_BATCH):
            end = min(start + PAGES_PER_BATCH - 1, total_pages)
            batches.append((start, end))

        print(f"{tag} {file_name}: {total_pages}p, {len(batches)} batches")

        # 提交所有批次到共享 executor
        futures = []
        for start, end in batches:
            future = executor.submit(
                process_single_batch, pdf_path, start, end, tmpdir, file_name,
            )
            futures.append(future)

        # 收集結果
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

        progress["completed"].append(file_id)
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

    pending = [
        p for p in sorted(pdfs, key=lambda x: x["size_mb"])
        if p["id"] not in completed_ids and p["size_mb"] <= 300
    ]

    total = len(pending)
    print(f"\nFast batch v2: {total} PDFs pending, {len(completed_ids)} done")
    print(f"Settings: DPI={DPI}, quality={JPEG_QUALITY}, pages/batch={PAGES_PER_BATCH}")
    print(f"Concurrency: {MAX_PDF_CONCURRENT} PDFs x {MAX_API_WORKERS} API workers\n")

    # 一個共享的 API worker pool
    with ThreadPoolExecutor(max_workers=MAX_API_WORKERS) as api_executor:
        # 多個 PDF 同時處理
        with ThreadPoolExecutor(max_workers=MAX_PDF_CONCURRENT) as pdf_executor:
            pdf_futures = []
            for i, pdf in enumerate(pending):
                future = pdf_executor.submit(
                    process_one_pdf, pdf, api_executor, progress, i + 1, total,
                )
                pdf_futures.append((future, pdf))

            try:
                for future, pdf in pdf_futures:
                    future.result()  # 等待完成，錯誤已在內部處理
            except KeyboardInterrupt:
                print("\nInterrupted, progress saved.")
                save_progress(progress)
                sys.exit(0)

    save_progress(progress)
    print(f"\nDone! Completed: {len(progress['completed'])}")

    import sqlite3
    conn = sqlite3.connect("data/questions.db")
    total_q = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    print(f"Total questions: {total_q}")


if __name__ == "__main__":
    main()
