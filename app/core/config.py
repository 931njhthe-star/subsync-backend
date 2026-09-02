"""애플리케이션 설정.

환경변수로부터 API 주소, DB 접속정보, 외부 API Key 등을 로드한다.
개발/운영 환경은 환경변수로 분리한다.
"""

import os


class Settings:
    ENV: str = os.getenv("ENV", "development")
    # DATABASE_URL, REDIS_URL, LLM_API_KEY 등은 각 단계에서 추가한다.


settings = Settings()
