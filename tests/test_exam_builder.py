from services.exam_builder import build_exam_pdf

SAMPLE_QUESTIONS = [
    {
        "id": 1, "chapter": "氣候變遷", "type": "choice",
        "content": "下列何者是主要溫室氣體？",
        "option_a": "CO2", "option_b": "N2", "option_c": "O2", "option_d": "H2",
        "answer": "A", "difficulty": 1
    },
    {
        "id": 2, "chapter": "氣候變遷", "type": "truefalse",
        "content": "溫室效應是地球暖化的主因",
        "option_a": None, "option_b": None, "option_c": None, "option_d": None,
        "answer": "T", "difficulty": 1
    }
]

def test_build_exam_returns_bytes():
    pdf = build_exam_pdf(SAMPLE_QUESTIONS)
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"  # PDF magic bytes

def test_build_exam_with_answer_key():
    pdf = build_exam_pdf(SAMPLE_QUESTIONS, include_answers=True)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 0
