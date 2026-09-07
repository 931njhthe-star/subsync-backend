-- 3. saved_words: 사용자가 저장한 단어
-- 선행 파일: 1. users.sql

CREATE TABLE IF NOT EXISTS public.saved_words (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id),
    word TEXT,
    saved_at TIMESTAMPTZ
);
