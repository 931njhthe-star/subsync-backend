"""애플리케이션 설정.

환경변수로부터 API 주소, DB 접속정보, 외부 API Key 등을 로드한다.
개발/운영 환경은 환경변수로 분리한다.
"""

import os


class Settings:
    """환경변수에서 읽은 애플리케이션 설정을 보관한다.

    설정 객체는 모듈 import 시 한 번 생성된다. 따라서 `.env`나 운영 환경변수의
    값을 변경한 뒤에는 서버를 재시작해야 새 설정이 반영된다. API key는 로그나
    소스 코드에 노출하지 않고 실행 환경에서만 주입한다.
    """

    ENV: str = os.getenv("ENV", "development")
    # Supabase Auth 설정. Google 로그인 자체는 Supabase Auth가 처리하고, 백엔드는
    # 아래 프로젝트 정보로 Access Token만 검증한다. 비밀 키는 소스에 기록하지 않는다.
    supabase_url: str = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    # HS256 프로젝트에서 /auth/v1/user 검증 API를 호출할 때 사용하는 publishable/anon key.
    supabase_key: str = os.getenv("SUPABASE_KEY", "").strip()
    supabase_jwt_audience: str = os.getenv(
        "SUPABASE_JWT_AUDIENCE", "authenticated"
    ).strip()
    # 비워 두면 {SUPABASE_URL}/auth/v1을 사용한다.
    supabase_jwt_issuer: str = os.getenv("SUPABASE_JWT_ISSUER", "").strip()
    # auto: HS256은 Auth API, 비대칭 키는 JWKS. 운영에서는 auto를 권장한다.
    supabase_auth_verification_mode: str = os.getenv(
        "SUPABASE_AUTH_VERIFICATION_MODE", "auto"
    ).strip().lower()
    supabase_jwks_cache_seconds: int = int(
        os.getenv("SUPABASE_JWKS_CACHE_SECONDS", "600")
    )
    supabase_auth_timeout_seconds: float = float(
        os.getenv("SUPABASE_AUTH_TIMEOUT_SECONDS", "5")
    )
    # 현재 구현에서는 아래 설정 중 Video Tutor 관련 값만 사용한다.
    # 외부 provider는 명시적으로 켠 경우에만 사용한다. 기본값은 로컬 fallback이다.
    # gemini/auto: Gemini -> Groq, groq: Groq -> Gemini 순서로 시도한다.
    llm_provider: str = os.getenv("LLM_PROVIDER", "stub").strip().lower()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    gemini_timeout_seconds: float = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "20"))
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

# 라우터 dependency가 공유하는 프로세스 단위 설정 인스턴스다.
settings = Settings()
