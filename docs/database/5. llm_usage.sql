-- 5. llm_usage: 사용자별 LLM 사용량 기록
-- 선행 파일: 1. users.sql

CREATE TABLE IF NOT EXISTS public.llm_usage (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id),
    provider TEXT,
    model_name TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    used_at TIMESTAMPTZ
);
