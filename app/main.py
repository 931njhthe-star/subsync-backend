"""FastAPI 애플리케이션 진입점과 익명 API 로그 미들웨어."""

from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import Response

from app.api.v1.auth import router as auth_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.dictionary import router as dictionary_router
from app.api.v1.tutor import router as tutor_router
from app.api.v1.words import router as words_router
from app.core.config import settings
from app.db.api_logs import ApiLogEntry, ApiLogRepository

logger = logging.getLogger(__name__)
api_log_repository = ApiLogRepository(
    url=settings.supabase_url,
    secret_key=settings.supabase_secret_key,
    timeout_seconds=settings.api_log_timeout_seconds,
)

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


async def _write_api_log_safely(entry: ApiLogEntry) -> None:
    """로그 저장 실패가 원래 API 응답을 방해하지 않게 기록한다."""

    try:
        await api_log_repository.write(entry)
    except Exception:  # pragma: no cover - background failure is environment-specific
        logger.warning("api_log_write_failed api_name=%s", entry.api_name)


@app.middleware("http")
async def write_api_log(request: Request, call_next) -> Response:
    """API 요청의 최소 운영 지표를 응답 전송 뒤 Supabase에 기록한다.

    요청 본문과 응답 본문은 학습 데이터와 개인 정보를 포함할 수 있어 저장하지
    않는다. 로그인 전에는 ``api_logs.user_id``를 ``NULL``로 기록한다.
    """

    request_id = uuid4().hex
    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # 예외 응답도 최소 운영 지표에는 남기되, 원래 예외 처리는 FastAPI에 맡긴다.
        if request.method != "OPTIONS" and request.url.path.startswith("/api/"):
            await _write_api_log_safely(
                ApiLogEntry(
                    api_name=f"{request.method} {request.url.path}",
                    response_time_ms=round((perf_counter() - started_at) * 1_000),
                    status_code=500,
                    success=False,
                    error_message="server_error",
                )
            )
        raise
    response.headers["X-Request-ID"] = request_id

    # CORS preflight, Swagger, health check와 프론트의 폐기된 event endpoint는 실제
    # 제품 API 사용량이 아니므로 제외한다. event endpoint 자체는 프론트에서 제거한다.
    if (
        request.method != "OPTIONS"
        and request.url.path.startswith("/api/")
        and request.url.path != "/api/v1/logs/event"
    ):
        status_code = response.status_code
        entry = ApiLogEntry(
            api_name=f"{request.method} {request.url.path}",
            response_time_ms=round((perf_counter() - started_at) * 1_000),
            status_code=status_code,
            success=200 <= status_code < 400,
            error_message=(
                None
                if status_code < 400
                else "client_error"
                if status_code < 500
                else "server_error"
            ),
        )
        # 실제 응답 전송 뒤 실행해 Supabase 지연이 Tutor 응답 시간을 늘리지 않게 한다.
        response.background = BackgroundTask(_write_api_log_safely, entry)

    return response


# 버전이 필요한 기능은 `/api/v1` 아래에 모아 이후 하위 호환성을 유지한다.
app.include_router(auth_router, prefix="/api/v1")
app.include_router(dictionary_router, prefix="/api/v1")
app.include_router(tutor_router, prefix="/api/v1")
app.include_router(words_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    """서버 프로세스가 HTTP 요청을 처리할 수 있는지 확인한다."""

    return {"status": "ok"}
