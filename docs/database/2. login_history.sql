-- 2. login_history: 사용자 로그인 및 접근 이력
-- 선행 파일: 1. users.sql

CREATE TABLE IF NOT EXISTS public.login_history (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id),
    login_at TIMESTAMPTZ,
    logout_at TIMESTAMPTZ,
    last_access_at TIMESTAMPTZ,
    login_success BOOLEAN
);
