-- ============================================================
-- iPAS Quiz System - Complete Supabase Migration
-- Run in Supabase Dashboard > SQL Editor
-- ============================================================

-- ============================================================
-- 1. QUESTIONS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS questions (
    id             BIGSERIAL PRIMARY KEY,
    chapter        TEXT NOT NULL,
    source_file    TEXT NOT NULL DEFAULT '',
    type           TEXT NOT NULL CHECK(type IN ('choice', 'truefalse', 'multichoice', 'scenario_choice', 'scenario_multichoice')),
    content        TEXT NOT NULL,
    option_a       TEXT,
    option_b       TEXT,
    option_c       TEXT,
    option_d       TEXT,
    answer         TEXT NOT NULL,
    difficulty     INTEGER NOT NULL CHECK(difficulty IN (1, 2, 3)),
    explanation    TEXT,
    scenario_id    TEXT,
    scenario_text  TEXT,
    chapter_group  TEXT,
    bank_id        TEXT NOT NULL DEFAULT 'ipas-netzero-mid',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_questions_bank_id ON questions(bank_id);
CREATE INDEX IF NOT EXISTS idx_questions_chapter_group ON questions(chapter_group);
CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(type);
CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty);

-- ============================================================
-- 2. QUIZ SESSIONS (tracks seen questions to avoid repeats)
-- ============================================================
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    session_id TEXT,
    seen_ids   JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quiz_sessions_user ON quiz_sessions(user_id);

-- ============================================================
-- 3. QUIZ HISTORY (answer log per user)
-- ============================================================
CREATE TABLE IF NOT EXISTS quiz_history (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    question_id     INTEGER NOT NULL,
    question_type   TEXT NOT NULL,
    chapter         TEXT,
    content_preview TEXT,
    is_correct      BOOLEAN NOT NULL,
    user_answer     TEXT NOT NULL,
    correct_answer  TEXT,
    answered_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quiz_history_user ON quiz_history(user_id, answered_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_history_question ON quiz_history(question_id);

-- ============================================================
-- 4. EXAM SESSIONS (timed exam state)
-- ============================================================
CREATE TABLE IF NOT EXISTS exam_sessions (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    bank_id          TEXT NOT NULL DEFAULT 'ipas-netzero-mid',
    question_ids     JSONB NOT NULL,
    shuffle_map      JSONB,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_min     INTEGER NOT NULL DEFAULT 60,
    submitted_at     TIMESTAMPTZ,
    score            INTEGER,
    total            INTEGER,
    tab_switches     INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'active',
    question_results JSONB
);

CREATE INDEX IF NOT EXISTS idx_exam_sessions_user ON exam_sessions(user_id, started_at DESC);

-- ============================================================
-- 5. WRONG NOTEBOOK (error tracking + bookmarks)
-- ============================================================
CREATE TABLE IF NOT EXISTS wrong_notebook (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    question_id     INTEGER NOT NULL,
    source          TEXT NOT NULL CHECK(source IN ('quiz', 'exam', 'bookmark')),
    wrong_count     INTEGER NOT NULL DEFAULT 1,
    first_wrong_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_wrong_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    bookmarked      BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(user_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_wrong_notebook_user ON wrong_notebook(user_id);
CREATE INDEX IF NOT EXISTS idx_wrong_notebook_user_bookmarked ON wrong_notebook(user_id, bookmarked);

-- ============================================================
-- 6. INVITE CODES + PRO TIER
-- ============================================================
CREATE TABLE IF NOT EXISTS invites (
    id            BIGSERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    max_uses      INTEGER NOT NULL DEFAULT 1,
    duration_days INTEGER NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_by    TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    label         TEXT
);

CREATE TABLE IF NOT EXISTS user_pro (
    id           BIGSERIAL PRIMARY KEY,
    user_id      TEXT NOT NULL,
    invite_id    BIGINT NOT NULL REFERENCES invites(id),
    activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    UNIQUE(user_id, invite_id)
);

CREATE INDEX IF NOT EXISTS idx_user_pro_user_expires ON user_pro(user_id, expires_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_pro_invite_id ON user_pro(invite_id);

CREATE TABLE IF NOT EXISTS daily_usage (
    id             BIGSERIAL PRIMARY KEY,
    user_id        TEXT NOT NULL,
    usage_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    question_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, usage_date)
);

-- ============================================================
-- 7. RPC FUNCTIONS
-- ============================================================

-- 7a. Get distinct chapter groups for a bank
CREATE OR REPLACE FUNCTION get_distinct_chapters(p_bank_id TEXT DEFAULT NULL)
RETURNS TABLE(chapter_group TEXT) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT q.chapter_group
    FROM questions q
    WHERE (p_bank_id IS NULL OR q.bank_id = p_bank_id)
      AND q.chapter_group IS NOT NULL
      AND q.chapter_group != ''
    ORDER BY q.chapter_group;
END;
$$ LANGUAGE plpgsql STABLE;

-- 7b. Get question statistics for a bank
CREATE OR REPLACE FUNCTION get_question_stats(p_bank_id TEXT DEFAULT NULL)
RETURNS JSON AS $$
DECLARE
    result JSON;
BEGIN
    SELECT json_build_object(
        'total', (SELECT COUNT(*) FROM questions WHERE (p_bank_id IS NULL OR bank_id = p_bank_id)),
        'by_chapter', (
            SELECT COALESCE(json_object_agg(chapter_group, cnt), '{}'::json)
            FROM (
                SELECT chapter_group, COUNT(*) as cnt
                FROM questions
                WHERE (p_bank_id IS NULL OR bank_id = p_bank_id)
                  AND chapter_group IS NOT NULL
                GROUP BY chapter_group
            ) sub
        ),
        'by_type', (
            SELECT COALESCE(json_object_agg(type, cnt), '{}'::json)
            FROM (
                SELECT type, COUNT(*) as cnt
                FROM questions
                WHERE (p_bank_id IS NULL OR bank_id = p_bank_id)
                GROUP BY type
            ) sub
        )
    ) INTO result;
    RETURN result;
END;
$$ LANGUAGE plpgsql STABLE;

-- 7c. Get weakness stats (per-chapter accuracy for a user)
CREATE OR REPLACE FUNCTION get_weakness_stats(p_user_id TEXT)
RETURNS TABLE(chapter TEXT, total BIGINT, correct BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT
        qh.chapter,
        COUNT(*)::BIGINT as total,
        SUM(CASE WHEN qh.is_correct THEN 1 ELSE 0 END)::BIGINT as correct
    FROM quiz_history qh
    WHERE qh.user_id = p_user_id
      AND qh.chapter IS NOT NULL
    GROUP BY qh.chapter
    ORDER BY total DESC;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================
-- 8. ROW LEVEL SECURITY (optional, recommended for production)
-- ============================================================
-- Enable RLS on user-facing tables (questions is public read)
ALTER TABLE quiz_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE exam_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE wrong_notebook ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_usage ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS, so backend still works.
-- These policies are for direct client access if needed later.
CREATE POLICY "Users can view own quiz history"
    ON quiz_history FOR SELECT
    USING (auth.uid()::text = user_id);

CREATE POLICY "Users can view own exam sessions"
    ON exam_sessions FOR SELECT
    USING (auth.uid()::text = user_id);

CREATE POLICY "Users can view own notebook"
    ON wrong_notebook FOR SELECT
    USING (auth.uid()::text = user_id);

CREATE POLICY "Users can view own usage"
    ON daily_usage FOR SELECT
    USING (auth.uid()::text = user_id);
