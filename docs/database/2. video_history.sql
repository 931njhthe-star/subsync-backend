-- 2. video_history: 영상 시청 이력
-- 선행 파일: 1. users.sql

CREATE TABLE IF NOT EXISTS public.video_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
    video_id VARCHAR(50) NOT NULL,
    video_title VARCHAR(255),
    last_timestamp FLOAT DEFAULT 0.0,
    watch_duration_sec INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
