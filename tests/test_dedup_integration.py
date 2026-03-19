import pytest
from unittest.mock import patch
from database import init_db, get_questions
from services.embedding_service import init_chroma, _chroma_cache as _client_cache
from services.question_generator import insert_question_with_dedup


def _fake_embed(text: str) -> list[float]:
    """Deterministic fake embedding based on text content."""
    import hashlib
    h = hashlib.md5(text.encode()).hexdigest()
    vec = []
    for i in range(768):
        idx = i % len(h)
        vec.append((int(h[idx], 16) - 8) / 8.0)
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


@pytest.fixture(autouse=True)
def setup_teardown(tmp_path):
    chroma_dir = str(tmp_path / "test_dedup_chroma")
    init_chroma(chroma_dir)
    yield chroma_dir
    _client_cache.clear()


def _make_question(content, chapter="測試"):
    return {
        "chapter": chapter, "source_file": "test.txt",
        "type": "choice", "content": content,
        "option_a": "A", "option_b": "B", "option_c": "C", "option_d": "D",
        "answer": "A", "difficulty": 1, "explanation": "測試解析"
    }


@patch("services.embedding_service._embed", side_effect=_fake_embed)
def test_insert_unique_question(mock_embed, setup_teardown):
    chroma_dir = setup_teardown
    q = _make_question("溫室氣體的主要來源有哪些？")
    result = insert_question_with_dedup(q, chroma_dir=chroma_dir)
    assert result["inserted"] is True
    assert result["question_id"] > 0


@patch("services.embedding_service._embed", side_effect=_fake_embed)
def test_insert_duplicate_question_is_skipped(mock_embed, setup_teardown):
    chroma_dir = setup_teardown
    q1 = _make_question("二氧化碳是最主要的溫室氣體")
    q2 = _make_question("二氧化碳是最主要的溫室氣體")  # exact same

    r1 = insert_question_with_dedup(q1, chroma_dir=chroma_dir)
    r2 = insert_question_with_dedup(q2, chroma_dir=chroma_dir)

    assert r1["inserted"] is True
    assert r2["inserted"] is False
    assert r2["similar_to"] is not None

    questions = get_questions()
    assert len(questions) == 1


@patch("services.embedding_service._embed", side_effect=_fake_embed)
def test_insert_different_questions_both_succeed(mock_embed, setup_teardown):
    chroma_dir = setup_teardown
    q1 = _make_question("溫室氣體排放量的計算方法")
    q2 = _make_question("Python 程式語言的發展歷史")

    r1 = insert_question_with_dedup(q1, chroma_dir=chroma_dir)
    r2 = insert_question_with_dedup(q2, chroma_dir=chroma_dir)

    assert r1["inserted"] is True
    assert r2["inserted"] is True

    questions = get_questions()
    assert len(questions) == 2
