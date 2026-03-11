import pytest
import os
import shutil
from database import init_db, insert_question, get_questions
from services.embedding_service import init_chroma, _client_cache
from services.question_generator import insert_question_with_dedup


@pytest.fixture(autouse=True)
def setup_teardown(tmp_path):
    db_path = str(tmp_path / "test_dedup.db")
    chroma_dir = str(tmp_path / "test_dedup_chroma")
    init_db(db_path)
    init_chroma(chroma_dir)
    yield db_path, chroma_dir
    _client_cache.clear()


def _make_question(content, chapter="測試"):
    return {
        "chapter": chapter, "source_file": "test.txt",
        "type": "choice", "content": content,
        "option_a": "A", "option_b": "B", "option_c": "C", "option_d": "D",
        "answer": "A", "difficulty": 1, "explanation": "測試解析"
    }


def test_insert_unique_question(setup_teardown):
    db_path, chroma_dir = setup_teardown
    q = _make_question("溫室氣體的主要來源有哪些？")
    result = insert_question_with_dedup(q, db_path=db_path, chroma_dir=chroma_dir)
    assert result["inserted"] is True
    assert result["question_id"] > 0


def test_insert_duplicate_question_is_skipped(setup_teardown):
    db_path, chroma_dir = setup_teardown
    q1 = _make_question("二氧化碳是最主要的溫室氣體")
    q2 = _make_question("二氧化碳是最重要的溫室氣體")

    r1 = insert_question_with_dedup(q1, db_path=db_path, chroma_dir=chroma_dir)
    r2 = insert_question_with_dedup(q2, db_path=db_path, chroma_dir=chroma_dir)

    assert r1["inserted"] is True
    assert r2["inserted"] is False
    assert r2["similar_to"] is not None

    questions = get_questions(db_path=db_path)
    assert len(questions) == 1


def test_insert_different_questions_both_succeed(setup_teardown):
    db_path, chroma_dir = setup_teardown
    q1 = _make_question("溫室氣體排放量的計算方法")
    q2 = _make_question("Python 程式語言的發展歷史")

    r1 = insert_question_with_dedup(q1, db_path=db_path, chroma_dir=chroma_dir)
    r2 = insert_question_with_dedup(q2, db_path=db_path, chroma_dir=chroma_dir)

    assert r1["inserted"] is True
    assert r2["inserted"] is True

    questions = get_questions(db_path=db_path)
    assert len(questions) == 2
