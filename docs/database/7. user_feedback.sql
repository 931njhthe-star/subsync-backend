-- 7. user_feedback: AI 답변에 대한 사용자 피드백
-- 선행 파일: 1. users.sql, 6. tutor_messages.sql

CREATE TABLE IF NOT EXISTS public.user_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID REFERENCES public.tutor_messages(id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    rating VARCHAR(10) NOT NULL, -- 'up' | 'down'
    reason VARCHAR(100),         -- '너무 길어요', '설명이 어려워요' 등
    created_at TIMESTAMPTZ DEFAULT NOW()
);
