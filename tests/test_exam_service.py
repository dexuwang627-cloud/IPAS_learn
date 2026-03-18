"""Tests for exam service pure functions."""
from datetime import datetime, timezone, timedelta
from services.exam_service import (
    shuffle_questions, unshuffle_answers, is_expired, calculate_penalty,
)


def _make_q(qid, q_type="choice", answer="A"):
    return {
        "id": qid, "type": q_type, "content": f"Q{qid}",
        "option_a": "Opt A", "option_b": "Opt B",
        "option_c": "Opt C", "option_d": "Opt D",
        "answer": answer, "difficulty": 1,
    }


def test_shuffle_deterministic():
    qs = [_make_q(i) for i in range(5)]
    s1, m1 = shuffle_questions(qs, seed=42)
    s2, m2 = shuffle_questions(qs, seed=42)
    assert [q["id"] for q in s1] == [q["id"] for q in s2]


def test_shuffle_different_seed():
    qs = [_make_q(i) for i in range(10)]
    s1, _ = shuffle_questions(qs, seed=1)
    s2, _ = shuffle_questions(qs, seed=2)
    assert [q["id"] for q in s1] != [q["id"] for q in s2]


def test_shuffle_preserves_count():
    qs = [_make_q(i) for i in range(5)]
    shuffled, smap = shuffle_questions(qs, seed=99)
    assert len(shuffled) == 5
    assert len(smap) == 5


def test_shuffle_options_remapped():
    qs = [_make_q(1, answer="A")]
    shuffled, smap = shuffle_questions(qs, seed=12345)
    # The answer should still be valid (one of A,B,C,D)
    assert shuffled[0]["answer"] in ("A", "B", "C", "D")
    # The shuffle_map should contain the original ID
    assert "1" in smap


def test_shuffle_truefalse_no_option_shuffle():
    qs = [{
        "id": 1, "type": "truefalse", "content": "Q1",
        "option_a": None, "option_b": None, "option_c": None, "option_d": None,
        "answer": "T", "difficulty": 1,
    }]
    shuffled, smap = shuffle_questions(qs, seed=42)
    assert shuffled[0]["answer"] == "T"
    # option_map should be identity for truefalse
    assert smap["1"]["option_map"] == {"A": "A", "B": "B", "C": "C", "D": "D"}


def test_unshuffle_answers():
    qs = [_make_q(1, answer="A")]
    shuffled, smap = shuffle_questions(qs, seed=42)
    # User selects the answer that maps to A
    option_map = smap["1"]["option_map"]
    # Find which new key maps to original A
    new_key = option_map["A"]
    user_answers = {"1": new_key}
    canonical = unshuffle_answers(user_answers, smap)
    assert canonical["1"] == "A"


def test_unshuffle_multichoice():
    qs = [_make_q(1, q_type="multichoice", answer="AC")]
    shuffled, smap = shuffle_questions(qs, seed=42)
    option_map = smap["1"]["option_map"]
    new_a = option_map["A"]
    new_c = option_map["C"]
    user_answers = {"1": new_a + new_c}
    canonical = unshuffle_answers(user_answers, smap)
    assert "".join(sorted(canonical["1"])) == "AC"


def test_is_expired_true():
    past = (datetime.now(timezone.utc) - timedelta(minutes=120)).isoformat()
    assert is_expired(past, 60) is True


def test_is_expired_false():
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    assert is_expired(recent, 60) is False


def test_calculate_penalty_basic():
    assert calculate_penalty(3, 80) == 74


def test_calculate_penalty_floor_zero():
    assert calculate_penalty(100, 10) == 0


def test_calculate_penalty_no_switches():
    assert calculate_penalty(0, 50) == 50


def test_input_not_mutated():
    """Ensure shuffle_questions does not mutate input."""
    qs = [_make_q(1)]
    original_answer = qs[0]["answer"]
    original_opt_a = qs[0]["option_a"]
    shuffle_questions(qs, seed=42)
    assert qs[0]["answer"] == original_answer
    assert qs[0]["option_a"] == original_opt_a
