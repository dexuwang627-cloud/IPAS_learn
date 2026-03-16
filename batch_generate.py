"""
批次從 Google Drive IPAS 資料夾產生題目。
支援中斷後續跑、rate limit 自動等待、進度追蹤。

用法：
    python batch_generate.py                    # 跑全部
    python batch_generate.py --max-files 10     # 只跑前 10 個
    python batch_generate.py --resume            # 從上次中斷處繼續
    python batch_generate.py --skip-large 100   # 跳過超過 100MB 的 PDF
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from database import init_db, migrate_add_explanation
from services.embedding_service import init_chroma
from services.drive_generator import generate_from_drive_pdf

PROGRESS_FILE = "data/batch_progress.json"
DRIVE_FILES = "data/drive_files.json"


def load_progress() -> dict:
    if Path(PROGRESS_FILE).exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": [], "failed": [], "skipped": []}


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


def run_batch(max_files: int = 0, resume: bool = True,
              skip_large_mb: float = 300, num_choice: int = 3,
              num_tf: int = 2):
    # 初始化
    init_db()
    migrate_add_explanation()
    init_chroma()

    pdfs = load_drive_files()
    progress = load_progress() if resume else {"completed": [], "failed": [], "skipped": []}
    completed_ids = set(progress["completed"])

    # 過濾
    pending = []
    for pdf in sorted(pdfs, key=lambda x: x["size_mb"]):
        if pdf["id"] in completed_ids:
            continue
        if pdf["size_mb"] > skip_large_mb:
            if pdf["id"] not in progress["skipped"]:
                progress["skipped"].append(pdf["id"])
                print(f"⏭️  跳過（{pdf['size_mb']:.0f}MB > {skip_large_mb}MB）: {pdf['path']}")
            continue
        pending.append(pdf)

    if max_files > 0:
        pending = pending[:max_files]

    total = len(pending)
    print(f"\n📊 批次處理統計：")
    print(f"   總 PDF 數量: {len(pdfs)}")
    print(f"   已完成: {len(completed_ids)}")
    print(f"   本次待處理: {total}")
    print(f"   跳過（過大）: {len(progress['skipped'])}")
    print(f"   失敗: {len(progress['failed'])}")
    print()

    for i, pdf in enumerate(pending):
        print(f"\n{'='*60}")
        print(f"📚 [{i+1}/{total}] {pdf['path']} ({pdf['size_mb']:.1f}MB)")
        print(f"{'='*60}")

        try:
            result = generate_from_drive_pdf(
                file_id=pdf["id"],
                file_name=pdf["name"],
                num_choice=num_choice,
                num_tf=num_tf,
            )
            progress["completed"].append(pdf["id"])
            save_progress(progress)

            print(f"\n📊 結果: 產生 {result['total_generated']} 題，"
                  f"入庫 {result['total_inserted']}，"
                  f"重複 {result['total_duplicates']}")

        except KeyboardInterrupt:
            print("\n\n⛔ 使用者中斷，進度已儲存。")
            save_progress(progress)
            sys.exit(0)

        except Exception as e:
            error_msg = str(e)
            print(f"\n❌ 錯誤: {error_msg}")

            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                print("⏳ Rate limit，等待 60 秒...")
                time.sleep(60)
                # 不標記為 failed，下次會重試
            else:
                progress["failed"].append({"id": pdf["id"], "path": pdf["path"], "error": error_msg[:200]})
                save_progress(progress)

    # 最終統計
    save_progress(progress)
    print(f"\n{'='*60}")
    print(f"✅ 批次處理完成！")
    print(f"   完成: {len(progress['completed'])}")
    print(f"   失敗: {len(progress['failed'])}")
    print(f"   跳過: {len(progress['skipped'])}")

    from database import get_stats
    stats = get_stats()
    print(f"\n📊 題庫總計: {stats['total']} 題")
    for chapter, count in sorted(stats["by_chapter"].items()):
        print(f"   {chapter}: {count} 題")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批次從 Google Drive 產生 IPAS 題目")
    parser.add_argument("--max-files", type=int, default=0, help="最多處理幾個檔案（0=全部）")
    parser.add_argument("--resume", action="store_true", default=True, help="從上次中斷處繼續")
    parser.add_argument("--fresh", action="store_true", help="從頭開始（忽略進度）")
    parser.add_argument("--skip-large", type=float, default=300, help="跳過超過 N MB 的 PDF")
    parser.add_argument("--num-choice", type=int, default=3, help="每批選擇題數量")
    parser.add_argument("--num-tf", type=int, default=2, help="每批是非題數量")
    args = parser.parse_args()

    run_batch(
        max_files=args.max_files,
        resume=not args.fresh,
        skip_large_mb=args.skip_large,
        num_choice=args.num_choice,
        num_tf=args.num_tf,
    )
