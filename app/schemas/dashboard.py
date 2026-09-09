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


class DashboardUser(BaseModel):
    """대시보드 화면에서 사용자 ID를 표시값으로 바꾸기 위한 최소 정보."""

    id: str
    google_account_id: str | None = None
    email: str | None = None
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class DashboardRecentActivity(BaseModel):
    """홈 화면에 표시할 최근 API 활동 한 건."""

    api_name: str = Field(description="HTTP 메서드와 API 경로")
    requested_at: datetime = Field(description="요청 시각(UTC)")
    response_time_ms: int = Field(ge=0, description="API 응답 처리 시간(ms)")
    status_code: int = Field(ge=100, le=599, description="HTTP 상태 코드")
    success: bool = Field(description="2xx/3xx 응답 여부")
    user_id: str | None = Field(default=None, description="요청을 발생시킨 사용자 ID")
    user_label: str | None = Field(default=None, description="관리자 화면에 표시할 사용자 식별자")


class DashboardUsageDetail(BaseModel):
    """AI 사용량 화면의 상세 요청 1건."""

    id: str | None = Field(default=None, description="llm_usage 행 ID")
    user_id: str | None = Field(default=None, description="요청을 발생시킨 사용자 ID")
    user_label: str | None = Field(default=None, description="관리자 화면에 표시할 사용자 식별자")
    provider: str = Field(description="LLM provider")
    model_name: str = Field(description="LLM 모델명")
    input_tokens: int = Field(ge=0, description="입력 토큰 수")
    output_tokens: int = Field(ge=0, description="출력 토큰 수")
    total_tokens: int = Field(ge=0, description="전체 토큰 수")
    used_at: datetime | None = Field(default=None, description="사용 시각(UTC)")
    finish_reason: str | None = Field(default=None, description="provider 완료 사유")
    provider_latency: int | None = Field(default=None, ge=0, description="provider 응답시간(ms)")
    success: bool | None = Field(default=None, description="완료 사유 기준 성공 여부")


class DashboardOverviewResponse(BaseModel):
    """Dashboard Home 화면에서 사용하는 운영 요약."""

    period: DashboardPeriod
    tracked_user_count: int = Field(
        ge=0,
        description="두 테이블에서 user_id가 실제로 기록된 고유 사용자 수(NULL 제외)",
    )
    registered_user_count: int = Field(
        default=0,
        ge=0,
        description="선택 기간에 가입한 사용자 수(users.created_at 기준)",
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
    recent_ai_activity: list[DashboardUsageDetail] = Field(
        default_factory=list,
        description="홈 화면에 표시할 최근 AI 활동 목록",
    )
    users: list[DashboardUser] = Field(
        default_factory=list,
        description="화면의 사용자 표시값과 가입일에 사용하는 사용자 목록",
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
    error_count: int = Field(default=0, ge=0, description="finish_reason 기준 실패 요청 수")
    error_rate: float | None = Field(default=None, ge=0, le=1, description="LLM 실패율")
    average_latency_ms: float | None = Field(default=None, ge=0, description="provider 평균 응답시간(ms)")
    p95_latency_ms: float | None = Field(default=None, ge=0, description="provider P95 응답시간(ms)")


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
    details: list[DashboardUsageDetail] = Field(
        default_factory=list,
        description="선택 기간의 AI 사용량 상세 요청 내역",
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
    p95_response_time_ms: float = Field(
        default=0,
        ge=0,
        description="endpoint P95 응답 시간(ms)",
    )


class DashboardRecentApiCall(BaseModel):
    """API 호출 화면에 표시할 최근 요청 한 건."""

    api_name: str = Field(description="HTTP 메서드와 API 경로")
    requested_at: datetime = Field(description="요청 시각(UTC)")
    response_time_ms: int = Field(ge=0, description="응답 처리 시간(ms)")
    status_code: int = Field(ge=100, le=599, description="HTTP 상태 코드")
    success: bool = Field(description="2xx/3xx 응답 여부")
    id: str | None = Field(default=None, description="api_logs 행 ID")
    user_id: str | None = Field(default=None, description="요청을 발생시킨 사용자 ID")
    user_label: str | None = Field(default=None, description="관리자 화면에 표시할 사용자 식별자")


class DashboardStatusCodeUsage(BaseModel):
    """HTTP 상태 코드별 API 요청 집계."""

    status_code: int = Field(ge=100, le=599, description="HTTP 상태 코드")
    request_count: int = Field(ge=0, description="상태 코드가 발생한 요청 수")
    success_count: int = Field(ge=0, description="성공 요청 수")
    failure_count: int = Field(ge=0, description="실패 요청 수")


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
    all_calls: list[DashboardRecentApiCall] = Field(
        default_factory=list,
        description="선택 기간 전체 API 호출 상세 목록",
    )
    status_codes: list[DashboardStatusCodeUsage] = Field(
        default_factory=list,
        description="HTTP 상태 코드별 요청 집계",
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
    "DashboardStatusCodeUsage",
    "DashboardUser",
    "DashboardUsageDetail",
    "DashboardUsageResponse",
    "DashboardUsageSummary",
]
