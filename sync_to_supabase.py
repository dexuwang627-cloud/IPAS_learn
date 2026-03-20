"""
Sync questions from local SQLite to Supabase PostgreSQL.
Strategy: Delete all → Re-insert all (ensures fixes/updates are applied).
"""
import json
import os
import sqlite3
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
REST_URL = f"{SUPABASE_URL}/rest/v1"
DB_PATH = "data/questions.db"
BATCH_SIZE = 100

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Prefer": "return=minimal",
}

count_headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Accept": "application/json",
    "Prefer": "count=exact",
    "Range": "0-0",
}


def count_supabase_questions() -> int:
    r = httpx.get(f"{REST_URL}/questions?select=id", headers=count_headers, timeout=10)
    cr = r.headers.get("content-range", "")
    if "/" in cr:
        return int(cr.split("/")[1])
    return 0


def delete_all_questions():
    """Delete all questions from Supabase."""
    print("Deleting all existing questions from Supabase...")
    r = httpx.delete(
        f"{REST_URL}/questions?id=gt.0",
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    print(f"  Deleted (status {r.status_code})")


def load_local_questions() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_batch(questions: list[dict]) -> int:
    """Insert a batch of questions into Supabase."""
    payload = []
    for q in questions:
        payload.append({
            "id": q["id"],
            "chapter": q["chapter"],
            "source_file": q["source_file"] or "",
            "type": q["type"],
            "content": q["content"],
            "option_a": q.get("option_a"),
            "option_b": q.get("option_b"),
            "option_c": q.get("option_c"),
            "option_d": q.get("option_d"),
            "answer": q["answer"],
            "difficulty": q["difficulty"],
            "explanation": q.get("explanation"),
            "scenario_id": q.get("scenario_id"),
            "scenario_text": q.get("scenario_text"),
            "chapter_group": q.get("chapter_group"),
            "bank_id": q.get("bank_id", "ipas-netzero-mid"),
            "created_at": q.get("created_at"),
        })

    r = httpx.post(
        f"{REST_URL}/questions",
        json=payload,
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return len(payload)


def main():
    print("=" * 50)
    print("iPAS Questions Sync: SQLite → Supabase")
    print("=" * 50)

    # Check current state
    sb_count = count_supabase_questions()
    questions = load_local_questions()
    print(f"Supabase: {sb_count} questions")
    print(f"SQLite:   {len(questions)} questions")

    if sb_count > 0:
        delete_all_questions()
        time.sleep(1)

    # Insert in batches
    total_inserted = 0
    batches = [questions[i:i + BATCH_SIZE] for i in range(0, len(questions), BATCH_SIZE)]
    print(f"\nInserting {len(questions)} questions in {len(batches)} batches...")

    for i, batch in enumerate(batches):
        inserted = insert_batch(batch)
        total_inserted += inserted
        print(f"  [{i + 1}/{len(batches)}] +{inserted} (total: {total_inserted})")
        time.sleep(0.2)

    # Verify
    time.sleep(1)
    final_count = count_supabase_questions()
    print(f"\nDone! Supabase now has {final_count} questions")

    if final_count == len(questions):
        print("SYNC SUCCESS")
    else:
        print(f"WARNING: Expected {len(questions)}, got {final_count}")

    # Verify a sample
    r = httpx.get(
        f"{REST_URL}/questions?id=eq.574&select=id,answer,content",
        headers={**headers, "Accept": "application/json"},
        timeout=10,
    )
    if r.status_code == 200 and r.json():
        q = r.json()[0]
        print(f"\nVerification sample - ID 574:")
        print(f"  answer={q['answer']} (should be F)")
        print(f"  content={q['content'][:50]}...")


if __name__ == "__main__":
    main()
