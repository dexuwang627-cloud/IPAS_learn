# Question Deduplication & Explanation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add semantic deduplication via ChromaDB + Ollama embeddings, and explanation field for every question.

**Architecture:** New `services/embedding_service.py` wraps Ollama `nomic-embed-text` + ChromaDB for vector storage. Dedup check happens before every DB insert. LLM prompt updated to generate explanations. DB schema gains `explanation` column. Frontend and PDF templates display explanations.

**Tech Stack:** ChromaDB, Ollama `nomic-embed-text`, SQLite, FastAPI, Jinja2, WeasyPrint

**Spec:** `docs/superpowers/specs/2026-03-11-dedup-explanation-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/embedding_service.py` | ChromaDB init, embed, query, add, remove |
| Create | `tests/test_embedding_service.py` | Unit tests for embedding service |
| Create | `tests/test_dedup_integration.py` | Integration test: insert_question_with_dedup |
| Create | `scripts/migrate_embeddings.py` | One-time migration of existing questions to ChromaDB |
| Create | `scripts/backfill_explanations.py` | Batch-generate explanations for existing questions |
| Modify | `requirements.txt` | Add `chromadb` |
| Modify | `database.py` | Add `explanation` column, return id from insert |
| Modify | `services/question_generator.py` | Update prompt for explanation, add dedup wrapper |
| Modify | `routers/generate.py` | Use dedup insert, report skipped count |
| Modify | `routers/quiz.py` | Include explanation in check response and PDF |
| Modify | `services/exam_builder.py` | Pass include_explanations to template |
| Modify | `templates/exam_template.html` | Render explanation below answers |
| Modify | `static/index.html` | Show explanation after grading and in bank |
| Modify | `main.py` | Init ChromaDB in lifespan |

---

## Chunk 1: Embedding Service + Dependencies

### Task 1: Add ChromaDB dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add chromadb to requirements.txt**

Add to the end of `requirements.txt`:
```
chromadb==0.6.3
```

- [ ] **Step 2: Install dependencies**

Run: `cd /Users/te-shuwang/ipas-quiz && pip install chromadb==0.6.3`

- [ ] **Step 3: Pull nomic-embed-text model**

Run: `ollama pull nomic-embed-text`

- [ ] **Step 4: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add requirements.txt
git commit -m "deps: add chromadb for vector-based question deduplication"
```

---

### Task 2: Create embedding service

**Files:**
- Create: `services/embedding_service.py`
- Create: `tests/test_embedding_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_embedding_service.py`:

```python
import pytest
import shutil
from services.embedding_service import init_chroma, add_question, find_similar, remove_question

TEST_CHROMA_DIR = "data/test_chroma"


@pytest.fixture(autouse=True)
def clean_chroma():
    """Each test gets a fresh ChromaDB."""
    yield
    shutil.rmtree(TEST_CHROMA_DIR, ignore_errors=True)


def test_init_chroma_returns_collection():
    collection = init_chroma(persist_dir=TEST_CHROMA_DIR)
    assert collection is not None
    assert collection.name == "questions"


def test_add_and_find_similar():
    init_chroma(persist_dir=TEST_CHROMA_DIR)
    add_question(1, "二氧化碳是主要的溫室氣體之一", chroma_dir=TEST_CHROMA_DIR)

    results = find_similar("二氧化碳是重要的溫室氣體", threshold=0.5, chroma_dir=TEST_CHROMA_DIR)
    assert len(results) >= 1
    assert results[0]["id"] == 1
    assert results[0]["similarity"] >= 0.5


def test_find_similar_no_match():
    init_chroma(persist_dir=TEST_CHROMA_DIR)
    add_question(1, "二氧化碳是主要的溫室氣體之一", chroma_dir=TEST_CHROMA_DIR)

    results = find_similar("Python 程式語言的歷史", threshold=0.85, chroma_dir=TEST_CHROMA_DIR)
    assert len(results) == 0


def test_remove_question():
    init_chroma(persist_dir=TEST_CHROMA_DIR)
    add_question(1, "碳足跡計算方法", chroma_dir=TEST_CHROMA_DIR)
    remove_question(1, chroma_dir=TEST_CHROMA_DIR)

    results = find_similar("碳足跡計算方法", threshold=0.3, chroma_dir=TEST_CHROMA_DIR)
    assert len(results) == 0


def test_add_duplicate_id_overwrites():
    init_chroma(persist_dir=TEST_CHROMA_DIR)
    add_question(1, "舊題目內容", chroma_dir=TEST_CHROMA_DIR)
    add_question(1, "新題目內容", chroma_dir=TEST_CHROMA_DIR)

    collection = init_chroma(persist_dir=TEST_CHROMA_DIR)
    assert collection.count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/te-shuwang/ipas-quiz && python -m pytest tests/test_embedding_service.py -v`
Expected: FAIL (import error — module not found)

- [ ] **Step 3: Implement embedding service**

Create `services/embedding_service.py`:

```python
"""
Embedding Service
ChromaDB + Ollama nomic-embed-text for semantic vector operations.
Used for question deduplication now; RAG retrieval later.
"""
import ollama
import chromadb

EMBED_MODEL = "nomic-embed-text"
DEFAULT_CHROMA_DIR = "data/chroma"
COLLECTION_NAME = "questions"

_client_cache: dict[str, chromadb.ClientAPI] = {}


def _get_client(persist_dir: str = DEFAULT_CHROMA_DIR) -> chromadb.ClientAPI:
    if persist_dir not in _client_cache:
        _client_cache[persist_dir] = chromadb.PersistentClient(path=persist_dir)
    return _client_cache[persist_dir]


def _embed(text: str) -> list[float]:
    response = ollama.embed(model=EMBED_MODEL, input=text)
    return response["embeddings"][0]


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/te-shuwang/ipas-quiz && python -m pytest tests/test_embedding_service.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add services/embedding_service.py tests/test_embedding_service.py
git commit -m "feat: add embedding service with ChromaDB for semantic question dedup"
```

---

## Chunk 2: Database Changes + Dedup Integration

### Task 3: Add explanation column and return id from insert

**Files:**
- Modify: `database.py`
- Modify: `tests/test_database.py`

- [ ] **Step 1: Write failing tests for new DB features**

Add to `tests/test_database.py`:

```python
def test_insert_question_returns_id():
    q = {
        "chapter": "氣候變遷", "source_file": "01.pdf",
        "type": "choice", "content": "測試題目",
        "option_a": "A", "option_b": "B", "option_c": "C", "option_d": "D",
        "answer": "A", "difficulty": 1
    }
    qid = insert_question(q, TEST_DB)
    assert isinstance(qid, int)
    assert qid > 0


def test_insert_question_with_explanation():
    q = {
        "chapter": "碳足跡", "source_file": "02.pdf",
        "type": "choice", "content": "碳足跡是什麼？",
        "option_a": "產品生命週期碳排放", "option_b": "每日步行距離",
        "option_c": "碳交易價格", "option_d": "森林面積",
        "answer": "A", "difficulty": 1,
        "explanation": "碳足跡指產品從原料到廢棄整個生命週期的溫室氣體排放總量。"
    }
    insert_question(q, TEST_DB)
    results = get_questions(db_path=TEST_DB)
    assert results[0]["explanation"] == q["explanation"]


def test_insert_question_without_explanation():
    q = {
        "chapter": "碳足跡", "source_file": "02.pdf",
        "type": "truefalse", "content": "CO2是溫室氣體",
        "option_a": None, "option_b": None, "option_c": None, "option_d": None,
        "answer": "T", "difficulty": 1
    }
    insert_question(q, TEST_DB)
    results = get_questions(db_path=TEST_DB)
    assert results[0]["explanation"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/te-shuwang/ipas-quiz && python -m pytest tests/test_database.py -v`
Expected: FAIL (insert_question returns None; no explanation column)

- [ ] **Step 3: Update database.py**

Modify `database.py`:

1. Add `explanation TEXT` to CREATE TABLE:
```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter     TEXT NOT NULL,
            source_file TEXT NOT NULL,
            type        TEXT NOT NULL CHECK(type IN ('choice', 'truefalse')),
            content     TEXT NOT NULL,
            option_a    TEXT,
            option_b    TEXT,
            option_c    TEXT,
            option_d    TEXT,
            answer      TEXT NOT NULL,
            difficulty  INTEGER NOT NULL CHECK(difficulty IN (1, 2, 3)),
            explanation TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
```

2. Update `insert_question` to include explanation and return id:
```python
def insert_question(q: dict, db_path: str = DEFAULT_DB) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.execute("""
        INSERT INTO questions
        (chapter, source_file, type, content, option_a, option_b, option_c, option_d, answer, difficulty, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        q["chapter"], q["source_file"], q["type"], q["content"],
        q.get("option_a"), q.get("option_b"), q.get("option_c"), q.get("option_d"),
        q["answer"], q["difficulty"], q.get("explanation")
    ))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id
```

3. Add migration helper for existing DB:
```python
def migrate_add_explanation(db_path: str = DEFAULT_DB):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("ALTER TABLE questions ADD COLUMN explanation TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/te-shuwang/ipas-quiz && python -m pytest tests/test_database.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add database.py tests/test_database.py
git commit -m "feat: add explanation column to questions table, return id from insert"
```

---

### Task 4: Dedup integration — insert_question_with_dedup

**Files:**
- Modify: `services/question_generator.py`
- Create: `tests/test_dedup_integration.py`

- [ ] **Step 1: Write failing integration test**

Create `tests/test_dedup_integration.py`:

```python
import pytest
import os
import shutil
from database import init_db, insert_question, get_questions
from services.embedding_service import init_chroma
from services.question_generator import insert_question_with_dedup

TEST_DB = "data/test_dedup.db"
TEST_CHROMA = "data/test_dedup_chroma"


@pytest.fixture(autouse=True)
def setup_teardown():
    os.makedirs("data", exist_ok=True)
    init_db(TEST_DB)
    init_chroma(TEST_CHROMA)
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    shutil.rmtree(TEST_CHROMA, ignore_errors=True)


def _make_question(content, chapter="測試"):
    return {
        "chapter": chapter, "source_file": "test.txt",
        "type": "choice", "content": content,
        "option_a": "A", "option_b": "B", "option_c": "C", "option_d": "D",
        "answer": "A", "difficulty": 1, "explanation": "測試解析"
    }


def test_insert_unique_question():
    q = _make_question("溫室氣體的主要來源有哪些？")
    result = insert_question_with_dedup(q, db_path=TEST_DB, chroma_dir=TEST_CHROMA)
    assert result["inserted"] is True
    assert result["question_id"] > 0


def test_insert_duplicate_question_is_skipped():
    q1 = _make_question("二氧化碳是最主要的溫室氣體")
    q2 = _make_question("二氧化碳是最重要的溫室氣體")

    r1 = insert_question_with_dedup(q1, db_path=TEST_DB, chroma_dir=TEST_CHROMA)
    r2 = insert_question_with_dedup(q2, db_path=TEST_DB, chroma_dir=TEST_CHROMA)

    assert r1["inserted"] is True
    assert r2["inserted"] is False
    assert r2["similar_to"] is not None

    questions = get_questions(db_path=TEST_DB)
    assert len(questions) == 1


def test_insert_different_questions_both_succeed():
    q1 = _make_question("溫室氣體排放量的計算方法")
    q2 = _make_question("Python 程式語言的發展歷史")

    r1 = insert_question_with_dedup(q1, db_path=TEST_DB, chroma_dir=TEST_CHROMA)
    r2 = insert_question_with_dedup(q2, db_path=TEST_DB, chroma_dir=TEST_CHROMA)

    assert r1["inserted"] is True
    assert r2["inserted"] is True

    questions = get_questions(db_path=TEST_DB)
    assert len(questions) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/te-shuwang/ipas-quiz && python -m pytest tests/test_dedup_integration.py -v`
Expected: FAIL (insert_question_with_dedup not found)

- [ ] **Step 3: Add insert_question_with_dedup to question_generator.py**

Add at end of `services/question_generator.py`:

```python
from database import insert_question as _db_insert
from services.embedding_service import add_question as _embed_add, find_similar as _embed_find


def insert_question_with_dedup(
    q: dict,
    threshold: float = 0.85,
    db_path: str = "data/questions.db",
    chroma_dir: str = "data/chroma",
) -> dict:
    """Insert question with semantic dedup check.
    Returns dict with inserted (bool), question_id, and similar_to if skipped."""
    similar = _embed_find(q["content"], threshold=threshold, chroma_dir=chroma_dir)
    if similar:
        return {
            "inserted": False,
            "question_id": None,
            "similar_to": similar[0],
        }

    qid = _db_insert(q, db_path=db_path)
    _embed_add(qid, q["content"], chroma_dir=chroma_dir)
    return {
        "inserted": True,
        "question_id": qid,
        "similar_to": None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/te-shuwang/ipas-quiz && python -m pytest tests/test_dedup_integration.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add services/question_generator.py tests/test_dedup_integration.py
git commit -m "feat: add insert_question_with_dedup for semantic deduplication"
```

---

## Chunk 3: LLM Prompt + Generation Router Updates

### Task 5: Update LLM prompt to generate explanations

**Files:**
- Modify: `services/question_generator.py`

- [ ] **Step 1: Update SYSTEM_PROMPT**

In `services/question_generator.py`, replace `SYSTEM_PROMPT` with:

```python
SYSTEM_PROMPT = """你是一位 iPAS 產業人才能力鑑定的出題專家。
你的任務是根據給定的學習教材內容，產生高品質的考試題目。

請嚴格遵守以下 JSON 格式輸出，不要輸出任何其他文字：

```json
[
  {
    "type": "choice",
    "content": "題目內容",
    "option_a": "選項A",
    "option_b": "選項B",
    "option_c": "選項C",
    "option_d": "選項D",
    "answer": "A",
    "difficulty": 1,
    "explanation": "說明正確答案的理由，並簡述干擾選項為何錯誤"
  },
  {
    "type": "truefalse",
    "content": "題目內容",
    "answer": "T",
    "difficulty": 2,
    "explanation": "說明該敘述為何正確或錯誤，引用教材中的具體內容"
  }
]
```

規則：
1. 選擇題 answer 只能是 A/B/C/D
2. 是非題 answer 只能是 T/F
3. difficulty 只能是 1(簡單)、2(中等)、3(困難)
4. 簡單題：定義、基本概念
5. 中等題：比較、應用、流程
6. 困難題：計算、整合分析、情境判斷
7. 題目必須基於給定教材內容，不可憑空捏造
8. 每題必須有明確唯一正確答案
9. explanation 必須基於教材內容，1-3 句話
10. 選擇題的 explanation 須說明正確選項理由，並提及至少一個干擾選項為何錯
11. 是非題的 explanation 須說明該敘述為何正確或錯誤
"""
```

- [ ] **Step 2: Update _parse_response to handle explanation**

In `_parse_response`, after the difficulty check (line 89), add:

```python
        # explanation is optional — don't discard question if missing
        if "explanation" not in q or not q.get("explanation"):
            q["explanation"] = None
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `cd /Users/te-shuwang/ipas-quiz && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add services/question_generator.py
git commit -m "feat: update LLM prompt to generate explanations for each question"
```

---

### Task 6: Update generation router to use dedup

**Files:**
- Modify: `routers/generate.py`

- [ ] **Step 1: Update _run_generation to use dedup**

Replace the `_run_generation` function and imports:

```python
from services.question_generator import generate_from_text_files, generate_questions, insert_question_with_dedup
from database import get_stats
```

Replace `_run_generation`:

```python
def _run_generation(num_choice: int, num_tf: int):
    """背景執行產題任務"""
    _generation_status["running"] = True
    _generation_status["last_result"] = None
    try:
        questions = generate_from_text_files(
            num_choice=num_choice, num_tf=num_tf
        )
        inserted = 0
        skipped = 0
        skipped_details = []
        for q in questions:
            try:
                result = insert_question_with_dedup(q)
                if result["inserted"]:
                    inserted += 1
                else:
                    skipped += 1
                    skipped_details.append({
                        "content": q["content"][:50],
                        "similar_to_id": result["similar_to"]["id"],
                        "similarity": result["similar_to"]["similarity"],
                    })
            except Exception as e:
                print(f"  插入失敗: {e}")
        _generation_status["last_result"] = {
            "generated": len(questions),
            "inserted": inserted,
            "skipped": skipped,
            "skipped_details": skipped_details,
            "stats": get_stats(),
        }
    except Exception as e:
        _generation_status["last_result"] = {"error": str(e)}
    finally:
        _generation_status["running"] = False
```

- [ ] **Step 2: Update generate_single to use dedup**

Replace the auto_save block in `generate_single`:

```python
    saved = 0
    skipped = 0
    if req.auto_save:
        for q in questions:
            result = insert_question_with_dedup(q)
            if result["inserted"]:
                saved += 1
            else:
                skipped += 1

    return {"generated": len(questions), "saved": saved, "skipped": skipped, "questions": questions}
```

- [ ] **Step 3: Remove old import**

Remove `from database import insert_question, get_stats` and replace with just `from database import get_stats` (insert_question is now called via insert_question_with_dedup).

- [ ] **Step 4: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add routers/generate.py
git commit -m "feat: generation routes use dedup insert, report skipped questions"
```

---

### Task 7: Init ChromaDB in app lifespan

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update lifespan to init ChromaDB**

```python
from database import init_db, migrate_add_explanation
from services.embedding_service import init_chroma


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    migrate_add_explanation()
    init_chroma()
    yield
```

- [ ] **Step 2: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add main.py
git commit -m "feat: init ChromaDB and migrate explanation column on app startup"
```

---

## Chunk 4: Frontend + PDF Display

### Task 8: Show explanation in quiz results and question bank

**Files:**
- Modify: `static/index.html`
- Modify: `routers/quiz.py`

- [ ] **Step 1: Update /quiz/check to include explanation**

In `routers/quiz.py`, update the `check_answers` results append:

```python
        results.append({
            "id": int(qid),
            "content": q["content"],
            "user_answer": user_answer,
            "correct_answer": q["answer"],
            "is_correct": is_correct,
            "explanation": q.get("explanation"),
        })
```

- [ ] **Step 2: Update frontend — quiz grading explanation display**

In `static/index.html`, in the `submitQuiz()` function, after the result tag creation (both correct and wrong branches), add explanation display. Replace the result tagging block (lines ~461-482) with:

After both the correct and wrong tag blocks, add this logic:

```javascript
    // Show explanation
    const explanation = r.explanation;
    if (explanation) {
      const expDiv = document.createElement('div');
      expDiv.style.cssText = 'margin-top:8px;padding:10px 14px;background:#f8fafc;border-radius:6px;font-size:13px;color:#475569;line-height:1.5;border-left:3px solid #94a3b8;';
      expDiv.textContent = explanation;
      card.appendChild(expDiv);
    }
```

- [ ] **Step 3: Update frontend — question bank explanation display**

In `static/index.html`, in the `loadBank()` function, after the answer line, add:

```javascript
      ${q.explanation ? `<div style="margin-top:4px;padding:8px 12px;background:#f8fafc;border-radius:6px;font-size:12px;color:#64748b;line-height:1.5;border-left:3px solid #94a3b8;">${q.explanation}</div>` : ''}
```

- [ ] **Step 4: Update frontend — generation status to show skipped**

In `static/index.html`, update the generation done message:

```javascript
        showGenStatus('done',
          `完成！產生 ${data.result.generated} 題，存入 ${data.result.inserted} 題，去重跳過 ${data.result.skipped || 0} 題。題庫總計 ${data.result.stats.total} 題。`);
```

And the last result message:

```javascript
        showGenStatus('done',
          `上次結果：產生 ${data.result.generated} 題，存入 ${data.result.inserted} 題，跳過 ${data.result.skipped || 0} 題。`);
```

- [ ] **Step 5: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add static/index.html routers/quiz.py
git commit -m "feat: display explanation in quiz results and question bank"
```

---

### Task 9: Add explanation to PDF template

**Files:**
- Modify: `templates/exam_template.html`
- Modify: `services/exam_builder.py`
- Modify: `routers/quiz.py`

- [ ] **Step 1: Add include_explanations parameter to exam_builder**

In `services/exam_builder.py`, update function signature and template render:

```python
def build_exam_pdf(questions: list[dict], include_answers: bool = False,
                   include_explanations: bool = False) -> bytes:
    choice_qs = [q for q in questions if q["type"] == "choice"]
    tf_qs = [q for q in questions if q["type"] == "truefalse"]
    chapters = list({q["chapter"] for q in questions})

    template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("exam_template.html")

    html_content = template.render(
        choice_questions=choice_qs,
        tf_questions=tf_qs,
        chapters="、".join(chapters),
        total=len(questions),
        date=date.today().strftime("%Y-%m-%d"),
        include_answers=include_answers,
        include_explanations=include_explanations,
    )

    return HTML(string=html_content).write_pdf()
```

- [ ] **Step 2: Update PDF template to render explanations**

In `templates/exam_template.html`, add CSS class:

```css
  .explanation { color: #555; font-size: 10pt; margin-top: 4px; margin-left: 20px;
                 padding: 4px 8px; background: #f5f5f5; border-left: 3px solid #ccc; }
```

After each answer line for choice questions:

```html
    {% if include_answers %}<div class="answer">答案：{{ q.answer }}</div>{% endif %}
    {% if include_explanations and q.explanation %}<div class="explanation">{{ q.explanation }}</div>{% endif %}
```

Same for true/false questions:

```html
    {% if include_answers %}<div class="answer">答案：{% if q.answer == 'T' %}O{% else %}X{% endif %}</div>{% endif %}
    {% if include_explanations and q.explanation %}<div class="explanation">{{ q.explanation }}</div>{% endif %}
```

- [ ] **Step 3: Add include_explanations to quiz PDF endpoint**

In `routers/quiz.py`, update `quiz_pdf`:

```python
@router.post("/quiz/pdf")
async def quiz_pdf(
    chapter: Optional[str] = Query(None),
    difficulty: Optional[int] = Query(None, ge=1, le=3),
    num_choice: int = Query(10, ge=0, le=50),
    num_tf: int = Query(5, ge=0, le=30),
    include_answers: bool = Query(False),
    include_explanations: bool = Query(False),
):
    ...
    pdf_bytes = build_exam_pdf(questions, include_answers=include_answers,
                               include_explanations=include_explanations)
    ...
```

- [ ] **Step 4: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add templates/exam_template.html services/exam_builder.py routers/quiz.py
git commit -m "feat: add explanation display to PDF exam template"
```

---

## Chunk 5: Migration Scripts

### Task 10: Create migration script for existing questions

**Files:**
- Create: `scripts/migrate_embeddings.py`

- [ ] **Step 1: Write migration script**

```python
"""
One-time migration: vectorize all existing questions into ChromaDB.
Also detects duplicates among existing questions.

Usage: python scripts/migrate_embeddings.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_questions, migrate_add_explanation
from services.embedding_service import init_chroma, add_question, find_similar

DB_PATH = "data/questions.db"
CHROMA_DIR = "data/chroma"


def migrate():
    migrate_add_explanation(DB_PATH)
    init_chroma(CHROMA_DIR)

    questions = get_questions(db_path=DB_PATH)
    print(f"Found {len(questions)} questions to migrate.\n")

    migrated = 0
    duplicates = []

    for q in questions:
        similar = find_similar(q["content"], threshold=0.85, chroma_dir=CHROMA_DIR)
        if similar:
            duplicates.append({
                "id": q["id"],
                "content": q["content"][:60],
                "similar_to_id": similar[0]["id"],
                "similar_content": similar[0]["content"][:60],
                "similarity": similar[0]["similarity"],
            })
            print(f"  DUPLICATE: #{q['id']} ~= #{similar[0]['id']} (similarity: {similar[0]['similarity']})")
        else:
            add_question(q["id"], q["content"], chroma_dir=CHROMA_DIR)
            migrated += 1

    print(f"\nMigration complete: {migrated} vectorized, {len(duplicates)} duplicates found.")
    if duplicates:
        print("\nDuplicate pairs (review and delete manually):")
        for d in duplicates:
            print(f"  #{d['id']}: {d['content']}")
            print(f"    ~= #{d['similar_to_id']}: {d['similar_content']} ({d['similarity']})")


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 2: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add scripts/migrate_embeddings.py
git commit -m "feat: add migration script to vectorize existing questions and detect duplicates"
```

---

### Task 11: Create backfill explanations script

**Files:**
- Create: `scripts/backfill_explanations.py`

- [ ] **Step 1: Write backfill script**

```python
"""
Batch-generate explanations for existing questions that lack them.

Usage: python scripts/backfill_explanations.py [--limit 50]
"""
import sys
import os
import argparse
import sqlite3
import ollama
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DEFAULT_DB

MODEL = "gemma3:4b"


def get_questions_without_explanation(db_path: str, limit: int) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM questions WHERE explanation IS NULL LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def generate_explanation(question: dict) -> str:
    if question["type"] == "choice":
        prompt = f"""以下是一題 iPAS 選擇題，請提供 1-3 句簡要解析，說明正確答案的理由。

題目：{question['content']}
(A) {question.get('option_a', '')}
(B) {question.get('option_b', '')}
(C) {question.get('option_c', '')}
(D) {question.get('option_d', '')}
正確答案：{question['answer']}

請直接輸出解析文字，不要加其他格式。"""
    else:
        correct = "正確" if question["answer"] == "T" else "錯誤"
        prompt = f"""以下是一題 iPAS 是非題，請提供 1-3 句簡要解析。

題目：{question['content']}
正確答案：{correct}

請直接輸出解析文字，不要加其他格式。"""

    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.3, "num_predict": 256},
    )
    return response["message"]["content"].strip()


def update_explanation(question_id: int, explanation: str, db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE questions SET explanation = ? WHERE id = ?",
        (explanation, question_id)
    )
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args()

    questions = get_questions_without_explanation(args.db, args.limit)
    print(f"Found {len(questions)} questions without explanation.\n")

    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] #{q['id']}: {q['content'][:50]}...")
        explanation = generate_explanation(q)
        update_explanation(q["id"], explanation, args.db)
        print(f"  -> {explanation[:80]}...")

    print(f"\nDone. {len(questions)} explanations generated.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add scripts/backfill_explanations.py
git commit -m "feat: add script to backfill explanations for existing questions"
```

---

### Task 12: Update delete route to also remove from ChromaDB

**Files:**
- Modify: `routers/questions.py`

- [ ] **Step 1: Update delete endpoint**

```python
from database import get_questions, get_chapters, get_stats, delete_question
from services.embedding_service import remove_question as remove_embedding

...

@router.delete("/questions/{question_id}")
async def remove_question(question_id: int):
    """刪除指定題目"""
    delete_question(question_id)
    try:
        remove_embedding(question_id)
    except Exception:
        pass  # ChromaDB entry may not exist for old questions
    return {"ok": True}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add routers/questions.py
git commit -m "feat: sync question deletion with ChromaDB"
```

---

### Task 13: Run full test suite and verify

- [ ] **Step 1: Run all tests**

Run: `cd /Users/te-shuwang/ipas-quiz && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run migration on existing DB**

Run: `cd /Users/te-shuwang/ipas-quiz && python scripts/migrate_embeddings.py`
Expected: Shows migrated count and any duplicates

- [ ] **Step 3: Start server and smoke test**

Run: `cd /Users/te-shuwang/ipas-quiz && uvicorn main:app --reload`
Test manually: open browser, try quiz, verify explanation shows after grading.

- [ ] **Step 4: Final commit**

```bash
cd /Users/te-shuwang/ipas-quiz
git add -A
git commit -m "chore: final verification — dedup and explanation features complete"
```
