-- llm_usage에 provider 응답 종료 사유와 HTTP 왕복 시간을 추가한다.
-- provider_latency는 밀리초 단위이며, provider가 메타데이터를 주지 않는 fallback은 NULL이다.
-- 적용 순서: 기존 llm_usage 테이블 생성 후 실행한다.

ALTER TABLE public.llm_usage
    ADD COLUMN IF NOT EXISTS finish_reason TEXT,
    ADD COLUMN IF NOT EXISTS provider_latency INTEGER;

-- ROLLBACK:
-- 이 컬럼에 기록된 종료 사유와 지연 시간은 삭제된다.
-- ALTER TABLE public.llm_usage
--     DROP COLUMN IF EXISTS finish_reason,
--     DROP COLUMN IF EXISTS provider_latency;
