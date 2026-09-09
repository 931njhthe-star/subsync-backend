-- saved_words 대소문자 중복 방지 migration
--
-- 적용 전 확인:
--   1. public.saved_words가 이미 존재하는지 확인한다.
--   2. 아래 migration은 기존 word 값을 lower(trim(word))로 채운다.
--   3. 이미 같은 user_id 안에 대소문자만 다른 중복 단어가 있으면 데이터 삭제를
--      자동으로 하지 않고 실패한다. 중복을 팀에서 확인·정리한 뒤 다시 실행한다.

ALTER TABLE public.saved_words
    ADD COLUMN IF NOT EXISTS word_lower TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.saved_words
        WHERE word IS NULL OR btrim(word) = ''
    ) THEN
        RAISE EXCEPTION
            'saved_words.word에 NULL 또는 빈 값이 있어 word_lower를 채울 수 없습니다.';
    END IF;
END
$$;

UPDATE public.saved_words
SET word_lower = lower(btrim(word))
WHERE word_lower IS NULL OR btrim(word_lower) = '';

DO $$
BEGIN
    IF EXISTS (
        SELECT user_id, word_lower
        FROM public.saved_words
        GROUP BY user_id, word_lower
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'saved_words에 사용자별 중복 단어가 있습니다. 중복을 정리한 뒤 다시 실행하세요.';
    END IF;
END
$$;

ALTER TABLE public.saved_words
    ALTER COLUMN word_lower SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS saved_words_user_word_lower_key
    ON public.saved_words (user_id, word_lower);

-- ROLLBACK:
-- DROP INDEX IF EXISTS public.saved_words_user_word_lower_key;
-- ALTER TABLE public.saved_words DROP COLUMN IF EXISTS word_lower;
