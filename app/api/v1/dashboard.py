"""Streamlit 관리자 대시보드용 운영 지표 조회 API."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import settings
from app.db.api_logs import ApiLogRepository
from app.db.llm_usage import LLMUsageRepository
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
_MAX_DASHBOARD_ROWS = 10_000


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


def _get_period(days: int) -> tuple[datetime, datetime]:
    """현재 시각 기준으로 대시보드의 UTC 조회 범위를 계산한다."""

    to_at = datetime.now(timezone.utc)
    return to_at - timedelta(days=days), to_at


async def _read_usage_rows(
    repository: LLMUsageRepository,
    *,
    from_at: datetime,
) -> list[dict[str, object]]:
    """사용량 조회 실패를 대시보드용 503 오류로 변환한다."""

    try:
        return await repository.list_recent(
            since=from_at,
            limit=_MAX_DASHBOARD_ROWS,
        )
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
) -> list[dict[str, object]]:
    """API 로그 조회 실패를 대시보드용 503 오류로 변환한다."""

    try:
        return await repository.list_recent(
            since=from_at,
            limit=_MAX_DASHBOARD_ROWS,
        )
    except Exception:
        logger.exception("dashboard_api_logs_read_failed")
        raise HTTPException(
            status_code=503,
            detail="API 로그를 조회할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from None


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
    usage_repository: LLMUsageRepository = Depends(
        get_dashboard_llm_usage_repository
    ),
    api_log_repository: ApiLogRepository = Depends(get_dashboard_api_log_repository),
) -> DashboardOverviewResponse:
    """Dashboard Home에 필요한 KPI·일별 AI 사용량·최근 활동을 반환한다.

    ``llm_usage``와 ``api_logs``를 같은 기간에 읽어 한 응답으로 합친다. 현재
    인증/관리자 권한 계층은 MVP 개발 모드라 연결 전이며, 운영 공개 전에는
    Supabase 관리자 JWT dependency를 이 라우터에 추가해야 한다.
    """

    from_at, to_at = _get_period(days)
    usage_rows, api_rows = await asyncio.gather(
        _read_usage_rows(usage_repository, from_at=from_at),
        _read_api_rows(api_log_repository, from_at=from_at),
    )
    return build_overview(
        usage_rows,
        api_rows,
        days=days,
        from_at=from_at,
        to_at=to_at,
        recent_limit=recent_limit,
    )


@router.get("/usage", response_model=DashboardUsageResponse)
async def get_dashboard_usage(
    days: int = Query(
        default=7,
        ge=1,
        le=90,
        description="최근 N일 기준 집계 기간",
    ),
    usage_repository: LLMUsageRepository = Depends(
        get_dashboard_llm_usage_repository
    ),
) -> DashboardUsageResponse:
    """AI 사용량 화면의 토큰 합계·provider/model·일별 데이터를 반환한다."""

    from_at, to_at = _get_period(days)
    rows = await _read_usage_rows(usage_repository, from_at=from_at)
    return build_usage(rows, days=days, from_at=from_at, to_at=to_at)


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
        le=100,
        description="최근 API 호출 최대 개수",
    ),
    api_log_repository: ApiLogRepository = Depends(get_dashboard_api_log_repository),
) -> DashboardApiCallsResponse:
    """API 호출 화면의 endpoint별 호출량·성공률·최근 상태를 반환한다."""

    from_at, to_at = _get_period(days)
    rows = await _read_api_rows(api_log_repository, from_at=from_at)
    return build_api_calls(
        rows,
        days=days,
        from_at=from_at,
        to_at=to_at,
        recent_limit=recent_limit,
    )


__all__ = [
    "get_dashboard_api_calls",
    "get_dashboard_api_log_repository",
    "get_dashboard_llm_usage_repository",
    "get_dashboard_overview",
    "get_dashboard_usage",
    "router",
]
