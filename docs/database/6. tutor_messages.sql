-- 6. tutor_messages: Video Tutor 주고받은 메시지
-- 선행 파일: 5. tutor_conversations.sql

CREATE TABLE IF NOT EXISTS public.tutor_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES public.tutor_conversations(id) ON DELETE CASCADE,
    sender VARCHAR(20) NOT NULL, -- 'user' | 'tutor' | 'proactive'
    message TEXT NOT NULL,
    timestamp FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tutor_messages_conv
    ON public.tutor_messages(conversation_id);
