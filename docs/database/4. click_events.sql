-- 4. click_events: 단어 클릭 이벤트 로그 (학습 행동 분석용)
-- 선행 파일: 1. users.sql

CREATE TABLE IF NOT EXISTS public.click_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    word VARCHAR(100) NOT NULL,
    video_id VARCHAR(50),
    timestamp FLOAT,
    context_sentence TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_click_events_word
    ON public.click_events(word);
