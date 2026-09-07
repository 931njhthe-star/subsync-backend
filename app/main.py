"""FastAPI 애플리케이션 진입점.

개발환경: uvicorn app.main:app --reload --port 8000
API 라우터는 app/api/ 에서 등록한다. (3단계~)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.tutor import router as tutor_router

# 모든 HTTP 라우트는 이 애플리케이션 객체에 등록된다. FastAPI는 이 객체를
# `uvicorn app.main:app` 명령으로 로드해 서버를 시작한다.
app = FastAPI(title="YouTube Language Teach Agent API")

# Content script의 fetch는 실행 중인 YouTube 페이지 origin으로 preflight를 보낼 수
# 있으므로 `chrome-extension://<id>`와 `https://www.youtube.com`을 함께 허용한다.
# 개발용 확장 프로그램과 로컬 대시보드만 허용하고, 실제 운영 origin은 배포 환경에서
# 별도로 제한한다.
_LOCAL_CORS_ORIGIN_REGEX = (
    r"^(chrome-extension://[A-Za-z0-9_-]+|https://www\.youtube\.com|"
    r"http://(?:localhost|127\.0\.0\.1)(?::\d+)?)$"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=_LOCAL_CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 버전이 필요한 기능은 `/api/v1` 아래에 모아 이후 하위 호환성을 유지한다.
app.include_router(tutor_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    """서버 프로세스가 HTTP 요청을 처리할 수 있는지 확인한다."""

    return {"status": "ok"}
