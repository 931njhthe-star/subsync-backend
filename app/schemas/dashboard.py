"""Streamlit 관리자 대시보드 조회 API의 응답 DTO."""

from __future__ import annotations

from datetime import date as date_type, datetime

from pydantic import BaseModel, Field


class DashboardPeriod(BaseModel):
    """대시보드 집계에 사용한 UTC 조회 기간."""

    days: int = Field(ge=1, le=90, description="조회 기간(일)")
    from_at: datetime = Field(description="조회 시작 시각(UTC)")
    to_at: datetime = Field(description="조회 종료 시각(UTC)")


class DashboardDailyUsage(BaseModel):
    """하루 단위 LLM 사용량 집계."""

    date: date_type = Field(description="UTC 기준 날짜")
    request_count: int = Field(ge=0, description="해당 날짜의 LLM 호출 횟수")
    input_tokens: int = Field(ge=0, description="해당 날짜의 입력 토큰 수")
    output_tokens: int = Field(ge=0, description="해당 날짜의 출력 토큰 수")
    total_tokens: int = Field(ge=0, description="해당 날짜의 총 토큰 수")


class DashboardRecentActivity(BaseModel):
    """홈 화면에 표시할 최근 API 활동 한 건."""

    api_name: str = Field(description="HTTP 메서드와 API 경로")
    requested_at: datetime = Field(description="요청 시각(UTC)")
    response_time_ms: int = Field(ge=0, description="API 응답 처리 시간(ms)")
    status_code: int = Field(ge=100, le=599, description="HTTP 상태 코드")
    success: bool = Field(description="2xx/3xx 응답 여부")


class DashboardOverviewResponse(BaseModel):
    """Dashboard Home 화면에서 사용하는 운영 요약."""

    period: DashboardPeriod
    tracked_user_count: int = Field(
        ge=0,
        description="두 테이블에서 user_id가 실제로 기록된 고유 사용자 수(NULL 제외)",
    )
    ai_call_count: int = Field(ge=0, description="llm_usage 기록 건수")
    api_request_count: int = Field(ge=0, description="api_logs 기록 건수")
    total_tokens: int = Field(ge=0, description="기간 내 누적 총 토큰 수")
    api_success_rate: float = Field(
        ge=0,
        le=1,
        description="기간 내 API 성공률(0~1), 요청이 없으면 0",
    )
    average_response_time_ms: float = Field(
        ge=0,
        description="기간 내 API 평균 응답 시간(ms), 요청이 없으면 0",
    )
    daily_ai_usage: list[DashboardDailyUsage] = Field(
        description="일별 AI 사용량. 데이터가 없는 날짜는 생략",
    )
    recent_activity: list[DashboardRecentActivity] = Field(
        description="최근 API 활동 목록",
    )


class DashboardUsageSummary(BaseModel):
    """AI 사용량 화면의 누적 토큰 요약."""

    request_count: int = Field(ge=0, description="LLM 호출 횟수")
    input_tokens: int = Field(ge=0, description="누적 입력 토큰 수")
    output_tokens: int = Field(ge=0, description="누적 출력 토큰 수")
    total_tokens: int = Field(ge=0, description="누적 총 토큰 수")
    average_tokens_per_request: float = Field(
        ge=0,
        description="호출당 평균 총 토큰 수, 호출이 없으면 0",
    )


class DashboardProviderUsage(BaseModel):
    """provider/model 조합별 LLM 사용량."""

    provider: str = Field(description="LLM provider")
    model_name: str = Field(description="LLM 모델명")
    request_count: int = Field(ge=0, description="호출 횟수")
    input_tokens: int = Field(ge=0, description="입력 토큰 수")
    output_tokens: int = Field(ge=0, description="출력 토큰 수")
    total_tokens: int = Field(ge=0, description="총 토큰 수")
    token_share: float = Field(
        ge=0,
        le=1,
        description="전체 총 토큰 중 해당 provider/model 비율(0~1)",
    )


class DashboardUsageResponse(BaseModel):
    """AI 사용량 화면에서 사용하는 provider·일별 상세 데이터."""

    period: DashboardPeriod
    summary: DashboardUsageSummary
    providers: list[DashboardProviderUsage] = Field(
        description="총 토큰 내림차순 provider/model 집계",
    )
    daily_usage: list[DashboardDailyUsage] = Field(
        description="날짜 오름차순 일별 집계",
    )


class DashboardApiSummary(BaseModel):
    """API 호출 화면의 요청·성공·지연 요약."""

    request_count: int = Field(ge=0, description="API 요청 횟수")
    success_count: int = Field(ge=0, description="성공 요청 횟수")
    failure_count: int = Field(ge=0, description="실패 요청 횟수")
    success_rate: float = Field(ge=0, le=1, description="API 성공률(0~1)")
    average_response_time_ms: float = Field(
        ge=0,
        description="평균 응답 시간(ms), 요청이 없으면 0",
    )
    p95_response_time_ms: int = Field(
        ge=0,
        description="응답 시간의 근사 p95(ms), 요청이 없으면 0",
    )


class DashboardEndpointUsage(BaseModel):
    """API 경로별 호출량과 성공률."""

    api_name: str = Field(description="HTTP 메서드와 API 경로")
    request_count: int = Field(ge=0, description="호출 횟수")
    success_count: int = Field(ge=0, description="성공 호출 횟수")
    failure_count: int = Field(ge=0, description="실패 호출 횟수")
    success_rate: float = Field(ge=0, le=1, description="endpoint 성공률(0~1)")
    average_response_time_ms: float = Field(
        ge=0,
        description="endpoint 평균 응답 시간(ms)",
    )


class DashboardRecentApiCall(BaseModel):
    """API 호출 화면에 표시할 최근 요청 한 건."""

    api_name: str = Field(description="HTTP 메서드와 API 경로")
    requested_at: datetime = Field(description="요청 시각(UTC)")
    response_time_ms: int = Field(ge=0, description="응답 처리 시간(ms)")
    status_code: int = Field(ge=100, le=599, description="HTTP 상태 코드")
    success: bool = Field(description="2xx/3xx 응답 여부")


class DashboardApiCallsResponse(BaseModel):
    """API 호출 화면에서 사용하는 endpoint별·최근 호출 데이터."""

    period: DashboardPeriod
    summary: DashboardApiSummary
    endpoints: list[DashboardEndpointUsage] = Field(
        description="호출 횟수 내림차순 endpoint 집계",
    )
    recent_calls: list[DashboardRecentApiCall] = Field(
        description="최근 요청 시각 내림차순 호출 목록",
    )


__all__ = [
    "DashboardApiCallsResponse",
    "DashboardApiSummary",
    "DashboardDailyUsage",
    "DashboardEndpointUsage",
    "DashboardOverviewResponse",
    "DashboardPeriod",
    "DashboardProviderUsage",
    "DashboardRecentActivity",
    "DashboardRecentApiCall",
    "DashboardUsageResponse",
    "DashboardUsageSummary",
]
