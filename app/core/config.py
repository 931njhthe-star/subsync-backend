"""애플리케이션 설정.

환경변수로부터 API 주소, DB 접속정보, 캐시 설정, 외부 API Key를 로드한다.
"""

import os


class Settings:
    """환경변수에서 읽은 애플리케이션 설정을 보관한다.

    설정 객체는 모듈 import 시 한 번 생성된다. 따라서 `.env`나 운영 환경변수의
    값을 변경한 뒤에는 서버를 재시작해야 새 설정이 반영된다. API key는 로그나
    소스 코드에 노출하지 않고 실행 환경에서만 주입한다.
    """

    ENV: str = os.getenv("ENV", "development")
    # API 로그는 서버 전용 키로만 기록한다. 로그인 전에는 user_id를 비워 익명
    # 운영 지표만 남긴다.
    supabase_url: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_secret_key: str = os.getenv("SUPABASE_SECRET_KEY", "")

    # 사전 조회는 Redis에 요청된 단어만 저장한다. REDIS_URL이 비어 있으면
    # Redis 없이도 외부 사전 API로 계속 동작하도록 서비스에서 처리한다.
    redis_url: str = os.getenv("REDIS_URL", "").strip()
    dictionary_cache_ttl_seconds: int = int(
        os.getenv("DICTIONARY_CACHE_TTL_SECONDS", "86400") or "86400"
    )
    dictionary_api_url: str = (
        os.getenv(
            "DICTIONARY_API_URL",
            "https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
        ).strip()
        or "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    )
    dictionary_timeout_seconds: float = float(
        os.getenv("DICTIONARY_TIMEOUT_SECONDS", "8") or "8"
    )
    deepl_api_key: str = os.getenv("DEEPL_API_KEY", "").strip()
    deepl_api_base_url: str = (
        os.getenv("DEEPL_API_BASE_URL", "https://api-free.deepl.com").strip()
        or "https://api-free.deepl.com"
    )
    deepl_timeout_seconds: float = float(
        os.getenv("DEEPL_TIMEOUT_SECONDS", "8") or "8"
    )
    api_log_timeout_seconds: float = float(
        os.getenv("API_LOG_TIMEOUT_SECONDS", "2")
    )
    # Tutor 사용량 저장도 API 로그와 같은 서버 전용 키를 사용한다. DB 지연이 응답을
    # 방해하지 않도록 별도 timeout을 둘 수 있다.
    llm_usage_timeout_seconds: float = float(
        os.getenv("LLM_USAGE_TIMEOUT_SECONDS", "2")
    )
    # 현재 구현에서는 아래 설정 중 Video Tutor 관련 값만 사용한다.
    # 외부 provider는 명시적으로 켠 경우에만 사용한다. 기본값은 로컬 fallback이다.
    # gemini/auto: Gemini -> Groq, groq: Groq -> Gemini 순서로 시도한다.
    llm_provider: str = os.getenv("LLM_PROVIDER", "stub").strip().lower()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    gemini_timeout_seconds: float = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "20"))
    tutor_max_output_tokens: int = int(
        os.getenv("TUTOR_MAX_OUTPUT_TOKENS", "512")
    )
    gemini_daily_token_limit: int = int(
        os.getenv("GEMINI_DAILY_TOKEN_LIMIT", "0")
    )
    gemini_minute_token_limit: int = int(
        os.getenv("GEMINI_MINUTE_TOKEN_LIMIT", "0")
    )
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    groq_timeout_seconds: float = float(os.getenv("GROQ_TIMEOUT_SECONDS", "20"))
    # Groq free plan을 가정한 보수적 기본값. 유료/상위 plan은 0 또는 실제 한도로 덮어쓴다.
    groq_daily_token_limit: int = int(
        os.getenv("GROQ_DAILY_TOKEN_LIMIT", "180000")
    )
    groq_minute_token_limit: int = int(
        os.getenv("GROQ_MINUTE_TOKEN_LIMIT", "7000")
    )
    # 선제 질문은 학습 흐름을 방해하지 않도록 영상 시점 기준으로 충분한 간격을 둔다.
    tutor_proactive_cooldown_seconds: float = float(
        os.getenv("TUTOR_PROACTIVE_COOLDOWN_SECONDS", "180")
    )
    # 영상당 선제 질문 수를 제한한다. 0이면 선제 질문을 표시하지 않는다.
    tutor_proactive_max_questions_per_video: int = int(
        os.getenv("TUTOR_PROACTIVE_MAX_QUESTIONS_PER_VIDEO", "3")
    )
    # 로그인 연동 전에는 anonymous actor별로, 운영 전환 후에는 사용자별로
    # 분당 Tutor 질문 수를 제한해 실수나 비용 폭증을 막는다. 0은 제한 없음이다.
    tutor_requests_per_minute: int = int(
        os.getenv("TUTOR_REQUESTS_PER_MINUTE", "30")
    )

# 라우터 dependency가 공유하는 프로세스 단위 설정 인스턴스다.
settings = Settings()
