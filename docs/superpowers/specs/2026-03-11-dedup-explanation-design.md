# Design: Question Deduplication & Explanation

**Date:** 2026-03-11
**Scope:** Semantic dedup via ChromaDB + Ollama embeddings; explanation field for questions
**Approach:** Option B (one-step infrastructure: embedding service + dedup + explanation)

## Context

- User is the sole operator; others receive PDF exports only
- Ollama runs locally with `gemma3:4b`; adding `nomic-embed-text` for embeddings
- ChromaDB chosen for vector storage (pure Python, persistent, zero-config)
- Future RAG will reuse the same ChromaDB + embedding infrastructure

## Section 1: Embedding Service

New file: `services/embedding_service.py`

- **Model:** `nomic-embed-text` (768-dim, Chinese support, via Ollama)
- **Storage:** ChromaDB `PersistentClient` at `data/chroma/`, collection name `questions`
- **Document ID:** SQLite `question_id` as string

Interface:
- `init_chroma()` — initialize client and collection
- `add_question(question_id, content)` — embed and store
- `find_similar(content, threshold=0.85)` — query nearest neighbors, return matches above threshold
- `remove_question(question_id)` — delete from ChromaDB

Decisions:
- Similarity threshold default: 0.85
- Synchronous embedding calls (low volume)
- ChromaDB auto-persists to disk

## Section 2: Dedup Flow

Trigger: before `insert_question()`, automatically.

Flow: generate question -> `find_similar(content)` -> if duplicate: skip and log; if unique: insert to SQLite -> add to ChromaDB.

Changes:
- `database.py`: `insert_question()` returns new row `id`
- New `insert_question_with_dedup()` wrapping dedup + insert + vectorize
- `routers/generate.py` and `scripts/generate_questions.py` call new function
- Generation results include `skipped` count and `skipped_details`

Migration:
- `scripts/migrate_embeddings.py`: one-time vectorization of existing questions
- Detects existing duplicates during migration, outputs report

## Section 3: Explanation Field

DB: add `explanation TEXT` column (nullable, backward-compatible).

LLM prompt changes:
- JSON schema adds `explanation` field
- Rules: based on source material, 1-3 sentences, explain correct answer and why distractors are wrong
- Validation: `explanation` optional in `_parse_response()`, missing = None (don't discard question)

Frontend:
- After grading: show explanation below correct/wrong tag (light gray block)
- Question bank: show explanation inline

PDF:
- New `include_explanations` parameter (independent from `include_answers`)
- Answer section shows explanation when enabled

Backfill:
- `scripts/backfill_explanations.py`: batch-generate explanations for existing questions via LLM
