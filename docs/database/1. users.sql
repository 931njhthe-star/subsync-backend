-- 1. users: Supabase Auth와 연결된 앱 사용자 정보
-- 실행 순서: auth.users에 사용자가 생성된 뒤 실행한다.

CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY REFERENCES auth.users(id),
    google_account_id TEXT UNIQUE,
    email TEXT,
    created_at TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ
);
