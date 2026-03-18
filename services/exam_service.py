"""
Exam mode service -- pure functions for shuffling, timer, and penalties.
"""
import random
from datetime import datetime, timezone, timedelta

_OPTION_KEYS = ["A", "B", "C", "D"]
_SHUFFLEABLE_TYPES = frozenset(
    {"choice", "multichoice", "scenario_choice", "scenario_multichoice"}
)


def shuffle_questions(
    questions: list[dict], seed: int
) -> tuple[list[dict], dict]:
    """Deterministically shuffle question order and option order.

    Returns (shuffled_questions, shuffle_map).
    shuffle_map: {"<question_id>": {"position": int, "option_map": {"A": "C", ...}}}
    """
    rng = random.Random(seed)
    indices = list(range(len(questions)))
    rng.shuffle(indices)

    shuffled = []
    shuffle_map = {}

    for new_pos, orig_idx in enumerate(indices):
        q = questions[orig_idx]
        qid = str(q["id"])

        if q.get("type") in _SHUFFLEABLE_TYPES and q.get("option_a"):
            new_q, option_map = _shuffle_options(q, rng)
        else:
            new_q = {**q}
            option_map = {k: k for k in _OPTION_KEYS}

        shuffled.append(new_q)
        shuffle_map[qid] = {"position": new_pos, "option_map": option_map}

    return shuffled, shuffle_map


def _shuffle_options(q: dict, rng: random.Random) -> tuple[dict, dict]:
    """Shuffle A/B/C/D options and remap the answer. Returns (new_q, option_map)."""
    available = [k for k in _OPTION_KEYS if q.get(f"option_{k.lower()}")]
    shuffled_keys = available[:]
    rng.shuffle(shuffled_keys)

    # option_map: original_key -> new_key (e.g., if A moved to slot C, map["A"] = "C")
    original_to_new = {}
    for new_slot, orig_key in zip(available, shuffled_keys):
        original_to_new[orig_key] = new_slot

    new_q = {**q}
    for orig_key in available:
        new_slot = original_to_new[orig_key]
        new_q[f"option_{new_slot.lower()}"] = q[f"option_{orig_key.lower()}"]

    # Remap answer
    answer = q.get("answer", "")
    new_answer = "".join(
        sorted(original_to_new.get(ch, ch) for ch in answer.upper())
    )
    new_q["answer"] = new_answer

    return new_q, original_to_new


def unshuffle_answers(
    answers: dict[str, str], shuffle_map: dict
) -> dict[str, str]:
    """Reverse option mapping to get canonical answers for grading."""
    result = {}
    for qid, user_answer in answers.items():
        mapping = shuffle_map.get(qid)
        if not mapping:
            result[qid] = user_answer
            continue

        option_map = mapping.get("option_map", {})
        # Reverse: new_key -> original_key
        reverse_map = {v: k for k, v in option_map.items()}

        canonical = "".join(
            sorted(reverse_map.get(ch, ch) for ch in user_answer.upper())
        )
        result[qid] = canonical

    return result


def is_expired(started_at_iso: str, duration_min: int) -> bool:
    """Check if exam time has passed based on server timestamp."""
    started = datetime.fromisoformat(started_at_iso.replace("Z", "+00:00"))
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    deadline = started + timedelta(minutes=duration_min)
    return datetime.now(timezone.utc) > deadline


def calculate_penalty(tab_switches: int, base_score: int) -> int:
    """Deduct 2 points per tab switch, minimum 0."""
    return max(0, base_score - tab_switches * 2)
