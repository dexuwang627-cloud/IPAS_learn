#!/usr/bin/env python3
"""
批次產題腳本 — 從 data/texts 中的教材自動產生題目存入 SQLite
用法: python scripts/generate_questions.py [--num-choice 3] [--num-tf 2]
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import init_db, insert_question, get_stats
from services.question_generator import generate_from_text_files


def main():
    parser = argparse.ArgumentParser(description="iPAS 自動產題")
    parser.add_argument("--num-choice", type=int, default=3, help="每份教材的選擇題數")
    parser.add_argument("--num-tf", type=int, default=2, help="每份教材的是非題數")
    parser.add_argument("--texts-dir", type=str, default="data/texts", help="文本目錄")
    args = parser.parse_args()

    print("🚀 iPAS 自動產題系統")
    print(f"   教材目錄: {args.texts_dir}")
    print(f"   每份教材: {args.num_choice} 選擇題 + {args.num_tf} 是非題")
    print()

    init_db()

    questions = generate_from_text_files(
        texts_dir=args.texts_dir,
        num_choice=args.num_choice,
        num_tf=args.num_tf,
    )

    print(f"\n📦 總共產生 {len(questions)} 題，開始寫入資料庫...")
    inserted = 0
    for q in questions:
        try:
            insert_question(q)
            inserted += 1
        except Exception as e:
            print(f"  ⚠️ 跳過: {e}")

    stats = get_stats()
    print(f"\n✅ 完成！成功寫入 {inserted} 題")
    print(f"📊 題庫統計: 總計 {stats['total']} 題")
    for ch, count in stats["by_chapter"].items():
        print(f"   - {ch}: {count} 題")


if __name__ == "__main__":
    main()
