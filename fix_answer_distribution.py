"""
修正選擇題答案分布：將 A/B/C/D 調整為各約 25%。
做法：隨機 shuffle 選項順序，純本地操作不需 API。
"""
import random
import sqlite3

DB_PATH = "data/questions.db"
TARGET_PER_ANSWER = None  # 自動計算


def shuffle_options(row):
    """將選項隨機重排，回傳新的 (option_a, option_b, option_c, option_d, answer)"""
    options = [
        ("A", row["option_a"]),
        ("B", row["option_b"]),
        ("C", row["option_c"]),
        ("D", row["option_d"]),
    ]
    correct_text = None
    for label, text in options:
        if label == row["answer"]:
            correct_text = text
            break

    texts = [text for _, text in options]
    random.shuffle(texts)

    new_answer = None
    labels = ["A", "B", "C", "D"]
    for i, text in enumerate(texts):
        if text == correct_text:
            new_answer = labels[i]
            break

    return texts[0], texts[1], texts[2], texts[3], new_answer


def main():
    random.seed(42)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 現狀
    rows = conn.execute(
        "SELECT answer, COUNT(*) as cnt FROM questions "
        "WHERE type='choice' GROUP BY answer ORDER BY answer"
    ).fetchall()
    total_choice = sum(r["cnt"] for r in rows)
    current = {r["answer"]: r["cnt"] for r in rows}

    print(f"修正前 ({total_choice} 題選擇題):")
    for ans in "ABCD":
        cnt = current.get(ans, 0)
        print(f"  {ans}: {cnt} ({cnt/total_choice*100:.1f}%)")

    target = total_choice // 4
    print(f"\n目標：每個答案約 {target} 題")

    # 找出需要減少的答案（超過 target）和需要增加的答案（低於 target）
    over = {ans: cnt - target for ans, cnt in current.items() if cnt > target}
    under = {ans: target - cnt for ans, cnt in current.items() if cnt < target}

    print(f"需要移出: {over}")
    print(f"需要移入: {under}")

    # 取得所有選擇題
    all_questions = conn.execute(
        "SELECT id, option_a, option_b, option_c, option_d, answer "
        "FROM questions WHERE type='choice'"
    ).fetchall()

    # 按答案分組
    by_answer = {}
    for q in all_questions:
        by_answer.setdefault(q["answer"], []).append(q)

    # 從過多的答案中隨機選題來 shuffle
    updates = []
    for over_ans, excess in sorted(over.items(), key=lambda x: -x[1]):
        candidates = list(by_answer[over_ans])
        random.shuffle(candidates)

        for q in candidates:
            if excess <= 0:
                break

            # shuffle 這題的選項
            new_a, new_b, new_c, new_d, new_ans = shuffle_options(q)

            # 只接受 shuffle 後答案變成需要增加的選項
            if new_ans in under and under[new_ans] > 0:
                updates.append((new_a, new_b, new_c, new_d, new_ans, q["id"]))
                under[new_ans] -= 1
                excess -= 1

    print(f"\n將 shuffle {len(updates)} 題")

    # 執行更新
    for new_a, new_b, new_c, new_d, new_ans, qid in updates:
        conn.execute(
            "UPDATE questions SET option_a=?, option_b=?, option_c=?, "
            "option_d=?, answer=? WHERE id=?",
            (new_a, new_b, new_c, new_d, new_ans, qid),
        )
    conn.commit()

    # 驗證
    rows = conn.execute(
        "SELECT answer, COUNT(*) as cnt FROM questions "
        "WHERE type='choice' GROUP BY answer ORDER BY answer"
    ).fetchall()
    print(f"\n修正後:")
    for r in rows:
        print(f"  {r['answer']}: {r['cnt']} ({r['cnt']/total_choice*100:.1f}%)")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
