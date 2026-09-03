-- ==============================================================================
-- SubSync Supabase PostgreSQL 스키마 정의서 (8개 핵심 테이블)
-- ==============================================================================

-- 1. users: 사용자 계정 정보
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    nickname VARCHAR(50),
    level VARCHAR(20) DEFAULT 'A2',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. video_history: 영상 시청 이력
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

-- 3. saved_words: 저장한 단어/표현
CREATE TABLE IF NOT EXISTS public.saved_words (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
    word VARCHAR(100) NOT NULL,
    meaning TEXT NOT NULL,
    video_id VARCHAR(50),
    timestamp FLOAT,
    context_sentence TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. click_events: 단어 클릭 이벤트 로그 (학습 행동 분석용)
CREATE TABLE IF NOT EXISTS public.click_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    word VARCHAR(100) NOT NULL,
    video_id VARCHAR(50),
    timestamp FLOAT,
    context_sentence TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. tutor_conversations: Video Tutor 대화 세션
CREATE TABLE IF NOT EXISTS public.tutor_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
    video_id VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. tutor_messages: Video Tutor 주고받은 메시지
CREATE TABLE IF NOT EXISTS public.tutor_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES public.tutor_conversations(id) ON DELETE CASCADE,
    sender VARCHAR(20) NOT NULL, -- 'user' | 'tutor' | 'proactive'
    message TEXT NOT NULL,
    timestamp FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. user_feedback: AI 답변에 대한 사용자 피드백
CREATE TABLE IF NOT EXISTS public.user_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID REFERENCES public.tutor_messages(id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    rating VARCHAR(10) NOT NULL, -- 'up' | 'down'
    reason VARCHAR(100),         -- '너무 길어요', '설명이 어려워요' 등
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 8. system_logs: API 응답시간, AI 지연시간 및 오류 로그 (대시보드 모니터링용)
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

-- 인덱스 생성 (조회 성능 최적화)
CREATE INDEX IF NOT EXISTS idx_saved_words_user ON public.saved_words(user_id);
CREATE INDEX IF NOT EXISTS idx_click_events_word ON public.click_events(word);
CREATE INDEX IF NOT EXISTS idx_tutor_messages_conv ON public.tutor_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_system_logs_event ON public.system_logs(event_type, created_at);
