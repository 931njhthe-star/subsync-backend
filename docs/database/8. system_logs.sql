-- 8. system_logs: API 응답시간, AI 지연시간 및 오류 로그 (대시보드 모니터링용)
-- 선행 파일: 1. users.sql

CREATE TABLE IF NOT EXISTS public.system_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(50) NOT NULL,
    user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    video_id VARCHAR(50),
    latency_ms INT,
    error_message TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_system_logs_event
    ON public.system_logs(event_type, created_at);
