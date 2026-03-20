import pytest
from unittest.mock import patch
from services.embedding_service import init_chroma, add_question, find_similar, remove_question, _chroma_cache as _client_cache


def _fake_embed(text: str) -> list[float]:
    """Deterministic fake embedding based on text hash for testing."""
    import hashlib
    h = hashlib.md5(text.encode()).hexdigest()
    # Convert hex to 768-dim float vector (Gemini embedding dimension)
    vec = []
    for i in range(768):
        idx = i % len(h)
        vec.append((int(h[idx], 16) - 8) / 8.0)
    # Normalize
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


@pytest.fixture(autouse=True)
def chroma_dir(tmp_path):
    """Each test gets a fresh ChromaDB in a unique temp directory."""
    d = str(tmp_path / "chroma")
    yield d
    _client_cache.clear()


@pytest.fixture(autouse=True)
def mock_embed():
    """Mock _embed to avoid hitting real Gemini API."""
    with patch("services.embedding_service._embed", side_effect=_fake_embed):
        yield


def test_init_chroma_returns_collection(chroma_dir):
    collection = init_chroma(persist_dir=chroma_dir)
    assert collection is not None
    assert collection.name == "questions"


def test_add_and_find_similar(chroma_dir):
    init_chroma(persist_dir=chroma_dir)
    add_question(1, "二氧化碳是主要的溫室氣體之一", chroma_dir=chroma_dir)

    results = find_similar("二氧化碳是主要的溫室氣體之一", threshold=0.5, chroma_dir=chroma_dir)
    assert len(results) >= 1
    assert results[0]["id"] == 1
    assert results[0]["similarity"] >= 0.5


def test_find_similar_no_match(chroma_dir):
    init_chroma(persist_dir=chroma_dir)
    add_question(1, "二氧化碳是主要的溫室氣體之一", chroma_dir=chroma_dir)

    results = find_similar("Python 程式語言的歷史", threshold=0.99, chroma_dir=chroma_dir)
    assert len(results) == 0


def test_remove_question(chroma_dir):
    init_chroma(persist_dir=chroma_dir)
    add_question(1, "碳足跡計算方法", chroma_dir=chroma_dir)
    remove_question(1, chroma_dir=chroma_dir)

    results = find_similar("碳足跡計算方法", threshold=0.3, chroma_dir=chroma_dir)
    assert len(results) == 0


def test_add_duplicate_id_overwrites(chroma_dir):
    init_chroma(persist_dir=chroma_dir)
    add_question(1, "舊題目內容", chroma_dir=chroma_dir)
    add_question(1, "新題目內容", chroma_dir=chroma_dir)

    collection = init_chroma(persist_dir=chroma_dir)
    assert collection.count() == 1
