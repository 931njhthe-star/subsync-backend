-- 4. ai_conversations: 영상별 AI 질문·답변과 피드백
-- 선행 파일: 1. users.sql

CREATE TABLE IF NOT EXISTS public.ai_conversations (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id),
    video_id TEXT,
    question TEXT,
    answer TEXT,
    started_at TIMESTAMPTZ,
    feedback JSONB
);
