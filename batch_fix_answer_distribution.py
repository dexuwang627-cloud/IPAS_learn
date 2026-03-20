"""
修復答案分布偏斜：隨機打亂選項順序，重新分配正確答案位置。
針對 answer=B 嚴重偏多的章節。
"""
import random
import sqlite3

DB_PATH = "data/questions.db"
random.seed(42)


def shuffle_options(question: dict) -> dict:
    """隨機打亂選項順序並更新答案"""
    options = [
        ("A", question["option_a"]),
        ("B", question["option_b"]),
        ("C", question["option_c"]),
        ("D", question["option_d"]),
    ]

    correct_letter = question["answer"]
    correct_text = dict(options)[correct_letter]

    # 打亂選項順序
    texts = [t for _, t in options]
    random.shuffle(texts)

    # 找到正確答案的新位置
    new_letters = ["A", "B", "C", "D"]
    new_answer = new_letters[texts.index(correct_text)]

    # 更新解析中的選項字母引用
    explanation = question["explanation"]
    # 建立舊字母 → 新字母的映射
    old_to_new = {}
    for old_letter, old_text in options:
        new_idx = texts.index(old_text)
        old_to_new[old_letter] = new_letters[new_idx]

    # 替換解析中的選項引用（用臨時標記避免衝突）
    for old_l, new_l in old_to_new.items():
        explanation = explanation.replace(f"選項{old_l}", f"選項__{new_l}__")
        explanation = explanation.replace(f"選項 {old_l}", f"選項 __{new_l}__")
    for new_l in "ABCD":
        explanation = explanation.replace(f"__{new_l}__", new_l)

    return {
        "id": question["id"],
        "option_a": texts[0],
        "option_b": texts[1],
        "option_c": texts[2],
        "option_d": texts[3],
        "answer": new_answer,
        "explanation": explanation,
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 找出需要修復的章節和題目
    # L211: B=21/37 (56.8%) → 需要打亂大部分 B 題
    chapters_to_fix = [
        "L211 組織節能減碳策略",
        "L222 碳移除與負碳技術",  # A=3 偏低
    ]

    total_fixed = 0

    for chapter in chapters_to_fix:
        rows = conn.execute(
            """SELECT id, content, option_a, option_b, option_c, option_d,
                      answer, explanation
               FROM questions
               WHERE chapter_group = ? AND type IN ('choice', 'scenario_choice')""",
            (chapter,),
        ).fetchall()

        questions = [dict(r) for r in rows]
        print(f"\n{chapter}: {len(questions)} 題")

        # 統計修復前
        before = {}
        for q in questions:
            before[q["answer"]] = before.get(q["answer"], 0) + 1
        print(f"  修復前: {before}")

        # 打亂所有題目的選項順序
        for q in questions:
            shuffled = shuffle_options(q)

            conn.execute(
                """UPDATE questions SET
                   option_a = ?, option_b = ?, option_c = ?, option_d = ?,
                   answer = ?, explanation = ?
                   WHERE id = ?""",
                (
                    shuffled["option_a"],
                    shuffled["option_b"],
                    shuffled["option_c"],
                    shuffled["option_d"],
                    shuffled["answer"],
                    shuffled["explanation"],
                    shuffled["id"],
                ),
            )
            total_fixed += 1

        conn.commit()

        # 統計修復後
        rows_after = conn.execute(
            """SELECT answer, COUNT(*) FROM questions
               WHERE chapter_group = ? AND type IN ('choice', 'scenario_choice')
               GROUP BY answer ORDER BY answer""",
            (chapter,),
        ).fetchall()
        after = {a: c for a, c in rows_after}
        print(f"  修復後: {after}")

    # 整體統計
    print(f"\n總共修復 {total_fixed} 題")
    print("\n整體選擇題答案分布:")
    rows = conn.execute(
        """SELECT answer, COUNT(*) FROM questions
           WHERE type IN ('choice', 'scenario_choice')
           GROUP BY answer ORDER BY answer"""
    ).fetchall()
    total = sum(c for _, c in rows)
    for a, c in rows:
        print(f"  {a}: {c} ({100 * c / total:.1f}%)")

    conn.close()


if __name__ == "__main__":
    main()
