-- ============================================================
-- iPAS Supabase Patch - 只補缺的部分
-- 在 Supabase Dashboard > SQL Editor 執行
-- ============================================================

-- 1. 建立缺少的 wrong_notebook 表
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

-- 2. 刪除舊的 RPC（如果存在但簽名不對）
DROP FUNCTION IF EXISTS get_distinct_chapters(TEXT);
DROP FUNCTION IF EXISTS get_distinct_chapters();
DROP FUNCTION IF EXISTS get_question_stats(TEXT);
DROP FUNCTION IF EXISTS get_question_stats();
DROP FUNCTION IF EXISTS get_weakness_stats(TEXT);

-- 3. 重建 RPC 函數
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

-- 4. RLS for wrong_notebook
ALTER TABLE wrong_notebook ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own notebook" ON wrong_notebook FOR SELECT USING (auth.uid()::text = user_id);
