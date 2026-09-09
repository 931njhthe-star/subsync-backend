"""Streamlit 관리자 대시보드용 운영 지표 조회 API."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import settings
from app.db.api_logs import ApiLogRepository
from app.db.llm_usage import LLMUsageRepository
from app.db.users import UserRepository
from app.schemas.dashboard import (
    DashboardApiCallsResponse,
    DashboardOverviewResponse,
    DashboardUsageResponse,
)
from app.services.dashboard import build_api_calls, build_overview, build_usage


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
logger = logging.getLogger(__name__)

# 부트캠프 규모에서는 Python에서 두 테이블을 읽어 집계한다. 무제한 조회로
# Dashboard 요청이 DB와 메모리를 동시에 압박하지 않도록 한 번의 상한을 둔다.
_MAX_DASHBOARD_ROWS = 50_000


@lru_cache(maxsize=1)
def get_dashboard_llm_usage_repository() -> LLMUsageRepository:
    """대시보드에서 공유할 ``llm_usage`` Supabase repository를 생성한다."""

    return LLMUsageRepository(
        url=settings.supabase_url,
        secret_key=settings.supabase_secret_key,
        timeout_seconds=settings.llm_usage_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_dashboard_api_log_repository() -> ApiLogRepository:
    """대시보드에서 공유할 ``api_logs`` Supabase repository를 생성한다."""

    return ApiLogRepository(
        url=settings.supabase_url,
        secret_key=settings.supabase_secret_key,
        timeout_seconds=settings.api_log_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_dashboard_user_repository() -> UserRepository:
    """대시보드에서 사용자 ID를 관리자용 표시값으로 바꿀 repository를 만든다."""

    return UserRepository(
        url=settings.supabase_url,
        secret_key=settings.supabase_secret_key,
        timeout_seconds=settings.auth_timeout_seconds,
    )


def _get_period(days: int) -> tuple[datetime, datetime]:
    """현재 시각 기준으로 대시보드의 UTC 조회 범위를 계산한다."""

    to_at = datetime.now(timezone.utc)
    return to_at - timedelta(days=days), to_at


def _resolve_period(
    days: int,
    from_date: date | None,
    to_date: date | None,
) -> tuple[int, datetime, datetime]:
    """days 또는 양 끝 날짜를 UTC 반개구간으로 변환한다."""

    if (from_date is None) != (to_date is None):
        raise HTTPException(
            status_code=422,
            detail="from_date와 to_date는 함께 입력해야 합니다.",
        )
    if from_date is None or to_date is None:
        from_at, to_at = _get_period(days)
        return days, from_at, to_at
    if to_date < from_date:
        raise HTTPException(
            status_code=422,
            detail="to_date는 from_date보다 빠를 수 없습니다.",
        )
    selected_days = (to_date - from_date).days + 1
    if selected_days > 90:
        raise HTTPException(
            status_code=422,
            detail="조회 기간은 최대 90일까지 선택할 수 있습니다.",
        )
    from_at = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
    to_at = datetime.combine(
        to_date + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )
    return selected_days, from_at, to_at


async def _list_recent_compat(
    repository: object,
    *,
    from_at: datetime,
    to_at: datetime,
) -> list[dict[str, object]]:
    """구형 테스트 repository도 새 기간 인자를 이해할 수 있게 호출한다."""

    list_recent = getattr(repository, "list_recent")
    try:
        return await list_recent(
            since=from_at,
            until=to_at,
            limit=_MAX_DASHBOARD_ROWS,
        )
    except TypeError as exc:
        if "until" not in str(exc):
            raise
        return await list_recent(since=from_at, limit=_MAX_DASHBOARD_ROWS)


async def _read_usage_rows(
    repository: LLMUsageRepository,
    *,
    from_at: datetime,
    to_at: datetime,
) -> list[dict[str, object]]:
    """사용량 조회 실패를 대시보드용 503 오류로 변환한다."""

    try:
        return await _list_recent_compat(repository, from_at=from_at, to_at=to_at)
    except Exception:
        logger.exception("dashboard_llm_usage_read_failed")
        raise HTTPException(
            status_code=503,
            detail="LLM 사용량을 조회할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from None


async def _read_api_rows(
    repository: ApiLogRepository,
    *,
    from_at: datetime,
    to_at: datetime,
) -> list[dict[str, object]]:
    """API 로그 조회 실패를 대시보드용 503 오류로 변환한다."""

    try:
        return await _list_recent_compat(repository, from_at=from_at, to_at=to_at)
    except Exception:
        logger.exception("dashboard_api_logs_read_failed")
        raise HTTPException(
            status_code=503,
            detail="API 로그를 조회할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from None


async def _read_user_rows(
    repository: UserRepository,
) -> list[dict[str, object]]:
    """사용자 표시값 조회 실패가 통계 API 전체를 중단시키지 않게 한다."""

    if not repository.is_configured:
        return []
    try:
        return await repository.list_directory(limit=_MAX_DASHBOARD_ROWS)
    except Exception:
        logger.warning("dashboard_users_read_failed", exc_info=True)
        return []


@router.get("/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(
    days: int = Query(
        default=7,
        ge=1,
        le=90,
        description="최근 N일 기준 집계 기간",
    ),
    recent_limit: int = Query(
        default=10,
        ge=1,
        le=100,
        description="홈 화면 최근 활동 최대 개수",
    ),
    from_date: date | None = Query(
        default=None,
        description="조회 시작일(YYYY-MM-DD, to_date와 함께 사용)",
    ),
    to_date: date | None = Query(
        default=None,
        description="조회 종료일(YYYY-MM-DD, 종료일 포함)",
    ),
    user_id: str | None = Query(default=None, description="사용자 ID 필터"),
    model_name: str | None = Query(default=None, description="LLM 모델 필터"),
    api_name: str | None = Query(default=None, description="API endpoint 필터"),
    usage_repository: LLMUsageRepository = Depends(
        get_dashboard_llm_usage_repository
    ),
    api_log_repository: ApiLogRepository = Depends(get_dashboard_api_log_repository),
    user_repository: UserRepository = Depends(get_dashboard_user_repository),
) -> DashboardOverviewResponse:
    """Dashboard Home에 필요한 KPI·일별 AI 사용량·최근 활동을 반환한다.

    ``llm_usage``와 ``api_logs``를 같은 기간에 읽어 한 응답으로 합친다. 현재
    인증/관리자 권한 계층은 MVP 개발 모드라 연결 전이며, 운영 공개 전에는
    Supabase 관리자 JWT dependency를 이 라우터에 추가해야 한다.
    """

    selected_days, from_at, to_at = _resolve_period(days, from_date, to_date)
    usage_rows, api_rows, user_rows = await asyncio.gather(
        _read_usage_rows(usage_repository, from_at=from_at, to_at=to_at),
        _read_api_rows(api_log_repository, from_at=from_at, to_at=to_at),
        _read_user_rows(user_repository),
    )
    return build_overview(
        usage_rows,
        api_rows,
        days=selected_days,
        from_at=from_at,
        to_at=to_at,
        recent_limit=recent_limit,
        user_rows=user_rows,
        user_id=user_id,
        model_name=model_name,
        api_name=api_name,
    )


@router.get("/usage", response_model=DashboardUsageResponse)
async def get_dashboard_usage(
    days: int = Query(
        default=7,
        ge=1,
        le=90,
        description="최근 N일 기준 집계 기간",
    ),
    from_date: date | None = Query(
        default=None,
        description="조회 시작일(YYYY-MM-DD, to_date와 함께 사용)",
    ),
    to_date: date | None = Query(
        default=None,
        description="조회 종료일(YYYY-MM-DD, 종료일 포함)",
    ),
    user_id: str | None = Query(default=None, description="사용자 ID 필터"),
    model_name: str | None = Query(default=None, description="LLM 모델 필터"),
    usage_repository: LLMUsageRepository = Depends(
        get_dashboard_llm_usage_repository
    ),
    user_repository: UserRepository = Depends(get_dashboard_user_repository),
) -> DashboardUsageResponse:
    """AI 사용량 화면의 토큰 합계·provider/model·일별 데이터를 반환한다."""

    selected_days, from_at, to_at = _resolve_period(days, from_date, to_date)
    rows, user_rows = await asyncio.gather(
        _read_usage_rows(usage_repository, from_at=from_at, to_at=to_at),
        _read_user_rows(user_repository),
    )
    return build_usage(
        rows,
        days=selected_days,
        from_at=from_at,
        to_at=to_at,
        user_rows=user_rows,
        user_id=user_id,
        model_name=model_name,
    )


@router.get("/api-calls", response_model=DashboardApiCallsResponse)
async def get_dashboard_api_calls(
    days: int = Query(
        default=7,
        ge=1,
        le=90,
        description="최근 N일 기준 집계 기간",
    ),
    recent_limit: int = Query(
        default=10,
        ge=1,
        le=50_000,
        description="최근 API 호출 최대 개수",
    ),
    from_date: date | None = Query(
        default=None,
        description="조회 시작일(YYYY-MM-DD, to_date와 함께 사용)",
    ),
    to_date: date | None = Query(
        default=None,
        description="조회 종료일(YYYY-MM-DD, 종료일 포함)",
    ),
    user_id: str | None = Query(default=None, description="사용자 ID 필터"),
    api_name: str | None = Query(default=None, description="API endpoint 필터"),
    api_log_repository: ApiLogRepository = Depends(get_dashboard_api_log_repository),
    user_repository: UserRepository = Depends(get_dashboard_user_repository),
) -> DashboardApiCallsResponse:
    """API 호출 화면의 endpoint별 호출량·성공률·최근 상태를 반환한다."""

    selected_days, from_at, to_at = _resolve_period(days, from_date, to_date)
    rows, user_rows = await asyncio.gather(
        _read_api_rows(api_log_repository, from_at=from_at, to_at=to_at),
        _read_user_rows(user_repository),
    )
    return build_api_calls(
        rows,
        days=selected_days,
        from_at=from_at,
        to_at=to_at,
        recent_limit=recent_limit,
        user_rows=user_rows,
        user_id=user_id,
        api_name=api_name,
    )


__all__ = [
    "get_dashboard_api_calls",
    "get_dashboard_api_log_repository",
    "get_dashboard_llm_usage_repository",
    "get_dashboard_user_repository",
    "get_dashboard_overview",
    "get_dashboard_usage",
    "router",
]
