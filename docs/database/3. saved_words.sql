-- 3. saved_words: 사용자가 저장한 단어
-- 선행 파일: 1. users.sql

CREATE TABLE IF NOT EXISTS public.saved_words (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id),
    word TEXT,
    word_lower TEXT NOT NULL,
    saved_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS saved_words_user_word_lower_key
    ON public.saved_words (user_id, word_lower);
