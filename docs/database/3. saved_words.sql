-- 3. saved_words: 저장한 단어/표현
-- 선행 파일: 1. users.sql

CREATE TABLE IF NOT EXISTS public.saved_words (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
    word VARCHAR(100) NOT NULL,
    meaning TEXT NOT NULL,
    video_id VARCHAR(50),
    timestamp FLOAT,
    context_sentence TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saved_words_user
    ON public.saved_words(user_id);
