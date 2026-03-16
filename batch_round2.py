"""
第二輪：加量出題 + 分難度出題
在第一輪基礎上，用更多題數和指定難度重跑，去重會自動擋掉重複題。
"""
import json
import os
import sys
import time
import tempfile
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from database import init_db, migrate_add_explanation
from services.embedding_service import init_chroma
from services.drive_generator import (
    list_drive_pdfs, download_pdf, get_pdf_page_count,
    _pdf_to_images, _generate_from_images,
    IPAS_FOLDER_ID, PAGES_PER_BATCH,
)
from services.question_generator import insert_question_with_dedup

PROGRESS_FILE = "data/batch_r2_progress.json"
DRIVE_FILES = "data/drive_files.json"


def load_progress() -> dict:
    if Path(PROGRESS_FILE).exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": [], "failed": [], "stats": {
        "total_generated": 0, "total_inserted": 0, "total_duplicates": 0,
    }}


def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def load_drive_files() -> list[dict]:
    with open(DRIVE_FILES) as f:
        all_files = json.load(f)
    return [
        f for f in all_files
        if f.get("size_mb", 0) > 0 and "google_type" not in f
    ]


def process_pdf_multi_difficulty(
    file_id: str, file_name: str, skip_large_mb: float = 300,
    size_mb: float = 0,
):
    """對一份 PDF 跑三個難度，每個難度出不同數量的題"""
    if size_mb > skip_large_mb:
        return None

    rounds = [
        {"num_choice": 5, "num_tf": 2, "difficulty": 1, "label": "簡單"},
        {"num_choice": 5, "num_tf": 3, "difficulty": 2, "label": "中等"},
        {"num_choice": 4, "num_tf": 2, "difficulty": 3, "label": "困難"},
    ]

    results = {"file_name": file_name, "generated": 0, "inserted": 0, "duplicates": 0}

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "source.pdf")
        print(f"  下載 {file_name}...")
        download_pdf(file_id, pdf_path)

        total_pages = get_pdf_page_count(pdf_path)
        print(f"  {total_pages} 頁")

        for round_cfg in rounds:
            diff = round_cfg["difficulty"]
            label = round_cfg["label"]
            num_c = round_cfg["num_choice"]
            num_tf = round_cfg["num_tf"]

            print(f"  [{label}] 出題中（{num_c}選擇+{num_tf}是非/批）...")

            for start in range(1, total_pages + 1, PAGES_PER_BATCH):
                end = min(start + PAGES_PER_BATCH - 1, total_pages)

                img_dir = os.path.join(tmpdir, f"d{diff}_{start}")
                os.makedirs(img_dir, exist_ok=True)
                image_paths = _pdf_to_images(pdf_path, start, end, img_dir)

                try:
                    questions = _generate_from_images(
                        image_paths, num_c, num_tf, diff,
                    )
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        print(f"    Rate limit, 等 60s...")
                        time.sleep(60)
                        try:
                            questions = _generate_from_images(
                                image_paths, num_c, num_tf, diff,
                            )
                        except Exception:
                            questions = []
                    else:
                        questions = []

                chapter = file_name.replace(".pdf", "")
                for q in questions:
                    q["chapter"] = chapter
                    q["source_file"] = f"{file_name} (p.{start}-{end},d{diff})"
                    result = insert_question_with_dedup(q)
                    if result["inserted"]:
                        results["inserted"] += 1
                    else:
                        results["duplicates"] += 1

                results["generated"] += len(questions)

            print(f"    [{label}] +{results['generated']} 題")

    return results


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
    print(f"\n第二輪：加量 + 分難度出題")
    print(f"待處理: {total} 個 PDF")
    print(f"已完成: {len(completed_ids)}")
    print()

    for i, pdf in enumerate(pending):
        print(f"\n[{i+1}/{total}] {pdf['path']} ({pdf['size_mb']:.1f}MB)")

        try:
            result = process_pdf_multi_difficulty(
                file_id=pdf["id"],
                file_name=pdf["name"],
                size_mb=pdf["size_mb"],
            )
            if result:
                progress["completed"].append(pdf["id"])
                progress["stats"]["total_generated"] += result["generated"]
                progress["stats"]["total_inserted"] += result["inserted"]
                progress["stats"]["total_duplicates"] += result["duplicates"]
                print(f"  結果: +{result['generated']}題, 入庫{result['inserted']}, 重複{result['duplicates']}")
            save_progress(progress)

        except KeyboardInterrupt:
            print("\n中斷，進度已儲存。")
            save_progress(progress)
            sys.exit(0)
        except Exception as e:
            print(f"  錯誤: {e}")
            progress["failed"].append({"id": pdf["id"], "error": str(e)[:200]})
            save_progress(progress)

    save_progress(progress)
    print(f"\n第二輪完成！")
    print(f"  總產生: {progress['stats']['total_generated']}")
    print(f"  總入庫: {progress['stats']['total_inserted']}")
    print(f"  總重複: {progress['stats']['total_duplicates']}")

    from database import get_stats
    stats = get_stats()
    print(f"\n題庫總計: {stats['total']} 題")


if __name__ == "__main__":
    main()
