-- =============================================================================
-- SubSync Supabase PostgreSQL 현재 테이블 스키마 (6개 테이블)
--
-- 이 파일은 같은 폴더의 번호 SQL을 한 파일로 모은 참조용 스냅샷이다.
-- 새 환경에서는 번호 SQL 또는 이 파일 중 하나만 실행한다.
-- =============================================================================

-- 1. users: Supabase Auth와 연결된 앱 사용자 정보
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY REFERENCES auth.users(id),
    google_account_id TEXT UNIQUE,
    email TEXT,
    created_at TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ
);

-- 2. login_history: 사용자 로그인 및 접근 이력
CREATE TABLE IF NOT EXISTS public.login_history (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id),
    login_at TIMESTAMPTZ,
    logout_at TIMESTAMPTZ,
    last_access_at TIMESTAMPTZ
);

-- 3. saved_words: 사용자가 저장한 단어
CREATE TABLE IF NOT EXISTS public.saved_words (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id),
    word TEXT,
    saved_at TIMESTAMPTZ
);

-- 4. ai_conversations: 영상별 AI 질문·답변과 피드백
CREATE TABLE IF NOT EXISTS public.ai_conversations (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id),
    video_id TEXT,
    question TEXT,
    answer TEXT,
    started_at TIMESTAMPTZ,
    feedback JSONB
);

-- 5. llm_usage: 사용자별 LLM 사용량 기록
CREATE TABLE IF NOT EXISTS public.llm_usage (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id),
    provider TEXT,
    model_name TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    used_at TIMESTAMPTZ,
    finish_reason TEXT,
    provider_latency INTEGER
);

-- 6. api_logs: API 요청 결과와 응답 시간 기록
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
