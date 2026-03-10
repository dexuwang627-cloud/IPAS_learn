import pytest
import os
from database import init_db, insert_question, get_questions, get_chapters

TEST_DB = "data/test_questions.db"

@pytest.fixture(autouse=True)
def setup_and_teardown():
    os.makedirs("data", exist_ok=True)
    init_db(TEST_DB)
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

def test_insert_and_get_question():
    q = {
        "chapter": "氣候變遷",
        "source_file": "01.pdf",
        "type": "choice",
        "content": "下列何者是溫室氣體？",
        "option_a": "CO2",
        "option_b": "N2",
        "option_c": "O2",
        "option_d": "Ar",
        "answer": "A",
        "difficulty": 1
    }
    insert_question(q, TEST_DB)
    results = get_questions(db_path=TEST_DB)
    assert len(results) == 1
    assert results[0]["chapter"] == "氣候變遷"

def test_get_chapters():
    q = {
        "chapter": "溫室氣體盤查",
        "source_file": "03.pdf",
        "type": "truefalse",
        "content": "CO2 是主要溫室氣體",
        "option_a": None, "option_b": None, "option_c": None, "option_d": None,
        "answer": "T",
        "difficulty": 2
    }
    insert_question(q, TEST_DB)
    chapters = get_chapters(TEST_DB)
    assert "溫室氣體盤查" in chapters

def test_get_questions_by_chapter_and_difficulty():
    for d in [1, 2, 3]:
        insert_question({
            "chapter": "產品碳足跡", "source_file": "05.pdf",
            "type": "choice", "content": f"題目{d}",
            "option_a": "A", "option_b": "B", "option_c": "C", "option_d": "D",
            "answer": "A", "difficulty": d
        }, TEST_DB)
    easy = get_questions(chapter="產品碳足跡", difficulty=1, db_path=TEST_DB)
    assert len(easy) == 1
