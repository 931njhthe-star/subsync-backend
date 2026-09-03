"""FastAPI 애플리케이션 진입점.

개발환경: uvicorn app.main:app --reload --port 8000
API 라우터는 app/api/ 에서 등록한다. (3단계~)
"""

from fastapi import FastAPI

from app.api.v1.tutor import router as tutor_router

# 모든 HTTP 라우트는 이 애플리케이션 객체에 등록된다. FastAPI는 이 객체를
# `uvicorn app.main:app` 명령으로 로드해 서버를 시작한다.
app = FastAPI(title="YouTube Language Teach Agent API")

# 버전이 필요한 기능은 `/api/v1` 아래에 모아 이후 하위 호환성을 유지한다.
app.include_router(tutor_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    """서버 프로세스가 HTTP 요청을 처리할 수 있는지 확인한다."""

    return {"status": "ok"}
