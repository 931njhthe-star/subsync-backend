-- 6. api_logs: API 요청 결과와 응답 시간 기록
-- 선행 파일: 1. users.sql

CREATE TABLE IF NOT EXISTS public.api_logs (
    id UUID PRIMARY KEY,
    api_name TEXT,
    user_id UUID REFERENCES public.users(id),
    requested_at TIMESTAMPTZ,
    response_time_ms INTEGER,
    status_code SMALLINT,
    success BOOLEAN,
    error_message TEXT
);
