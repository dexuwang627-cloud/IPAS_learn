"""
Embedding Service
ChromaDB + Gemini text-embedding-004 for semantic vector operations.
Used for question deduplication now; RAG retrieval later.
"""
import os

from google import genai
import chromadb

_api_key = os.environ.get("GEMINI_API_KEY")
_client = genai.Client(api_key=_api_key) if _api_key else None

EMBED_MODEL = "gemini-embedding-001"
DEFAULT_CHROMA_DIR = "data/chroma"
COLLECTION_NAME = "questions"

_chroma_cache: dict[str, chromadb.ClientAPI] = {}


def _get_client(persist_dir: str = DEFAULT_CHROMA_DIR) -> chromadb.ClientAPI:
    if persist_dir not in _chroma_cache:
        _chroma_cache[persist_dir] = chromadb.PersistentClient(path=persist_dir)
    return _chroma_cache[persist_dir]


def _embed(text: str) -> list[float]:
    result = _client.models.embed_content(model=EMBED_MODEL, contents=text)
    return result.embeddings[0].values


def init_chroma(persist_dir: str = DEFAULT_CHROMA_DIR):
    client = _get_client(persist_dir)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def add_question(question_id: int, content: str,
                 chroma_dir: str = DEFAULT_CHROMA_DIR):
    collection = init_chroma(chroma_dir)
    embedding = _embed(content)
    collection.upsert(
        ids=[str(question_id)],
        embeddings=[embedding],
        documents=[content],
    )


def find_similar(content: str, threshold: float = 0.85,
                 n_results: int = 5,
                 chroma_dir: str = DEFAULT_CHROMA_DIR) -> list[dict]:
    collection = init_chroma(chroma_dir)
    if collection.count() == 0:
        return []

    embedding = _embed(content)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=min(n_results, collection.count()),
        include=["documents", "distances"],
    )

    matches = []
    for i, doc_id in enumerate(results["ids"][0]):
        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        # Convert to similarity: 1 - (distance / 2)
        distance = results["distances"][0][i]
        similarity = 1 - (distance / 2)
        if similarity >= threshold:
            matches.append({
                "id": int(doc_id),
                "content": results["documents"][0][i],
                "similarity": round(similarity, 4),
            })

    return sorted(matches, key=lambda x: x["similarity"], reverse=True)


def remove_question(question_id: int,
                    chroma_dir: str = DEFAULT_CHROMA_DIR):
    collection = init_chroma(chroma_dir)
    collection.delete(ids=[str(question_id)])
