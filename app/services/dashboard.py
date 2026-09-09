"""대시보드 API에서 사용하는 ``llm_usage``·``api_logs`` 집계 로직."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from math import ceil
from typing import Iterable, Mapping

from app.schemas.dashboard import (
    DashboardApiCallsResponse,
    DashboardApiSummary,
    DashboardDailyUsage,
    DashboardEndpointUsage,
    DashboardOverviewResponse,
    DashboardPeriod,
    DashboardProviderUsage,
    DashboardRecentActivity,
    DashboardRecentApiCall,
    DashboardStatusCodeUsage,
    DashboardUser,
    DashboardUsageDetail,
    DashboardUsageResponse,
    DashboardUsageSummary,
)


Row = Mapping[str, object]


def _optional_text_value(row: Row, key: str) -> str | None:
    """DB 행의 식별자 필드를 빈 문자열 없이 선택값으로 반환한다."""

    value = row.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _user_labels(rows: Iterable[Row]) -> dict[str, str]:
    """users 행에서 API 응답에 사용할 관리자용 사용자 표시값을 만든다."""

    labels: dict[str, str] = {}
    for row in rows:
        user_id = _optional_text_value(row, "id")
        if not user_id:
            continue
        label = (
            _optional_text_value(row, "email")
            or _optional_text_value(row, "google_account_id")
            or user_id
        )
        labels[user_id] = label
    return labels


def _dashboard_users(rows: Iterable[Row]) -> list[DashboardUser]:
    """users 원본을 홈 화면에서 사용할 최소 사용자 DTO로 변환한다."""

    users: list[DashboardUser] = []
    for row in rows:
        user_id = _optional_text_value(row, "id")
        if not user_id:
            continue
        users.append(
            DashboardUser(
                id=user_id,
                google_account_id=_optional_text_value(row, "google_account_id"),
                email=_optional_text_value(row, "email"),
                created_at=_timestamp_value(row, "created_at"),
                last_login_at=_timestamp_value(row, "last_login_at"),
            )
        )
    return users


def _registered_user_count(
    rows: Iterable[Row],
    *,
    from_at: datetime,
    to_at: datetime,
) -> int:
    """users.created_at 기준으로 선택 기간의 가입자 수를 센다."""

    user_ids: set[str] = set()
    for row in rows:
        user_id = _optional_text_value(row, "id")
        created_at = _timestamp_value(row, "created_at")
        if user_id and created_at is not None and from_at <= created_at < to_at:
            user_ids.add(user_id)
    return len(user_ids)


def _filtered_rows(
    rows: Iterable[Row],
    *,
    user_id: str | None = None,
    model_name: str | None = None,
    api_name: str | None = None,
) -> list[Row]:
    """대시보드 API의 선택 필터를 동일한 규칙으로 적용한다."""

    filters = {
        key: value.strip().lower()
        for key, value in (
            ("user_id", user_id),
            ("model_name", model_name),
            ("api_name", api_name),
        )
        if value and value.strip()
    }
    if not filters:
        return list(rows)
    return [
        row
        for row in rows
        if all(str(row.get(key) or "").strip().lower() == value for key, value in filters.items())
    ]


def _int_value(row: Row, key: str) -> int:
    """DB 행의 숫자 값을 음수가 아닌 정수로 정규화한다."""

    try:
        return max(int(row.get(key) or 0), 0)
    except (TypeError, ValueError):
        # 외부 DB 응답은 신뢰할 수 없는 입력으로 보고, 한 행의 이상 값이
        # 전체 대시보드 응답을 깨뜨리지 않도록 해당 지표를 0으로 보정한다.
        return 0


def _text_value(row: Row, key: str, fallback: str = "unknown") -> str:
    """DB 행의 텍스트 값을 공백 없는 문자열로 정규화한다."""

    value = row.get(key)
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _timestamp_value(row: Row, key: str) -> datetime | None:
    """Supabase timestamp를 UTC aware ``datetime``으로 변환한다."""

    value = row.get(key)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bool_value(row: Row, key: str) -> bool:
    """Supabase REST 응답의 boolean 값을 안전하게 해석한다."""

    value = row.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "t", "yes"}
    return bool(value)


def _success_rate(success_count: int, request_count: int) -> float:
    """요청 수가 0일 때도 일관된 0을 반환하는 성공률을 계산한다."""

    if request_count <= 0:
        return 0.0
    return round(success_count / request_count, 4)


def _period(days: int, from_at: datetime, to_at: datetime) -> DashboardPeriod:
    """라우터의 조회 경계를 응답 DTO로 변환한다."""

    return DashboardPeriod(days=days, from_at=from_at, to_at=to_at)


def _daily_usage(rows: Iterable[Row]) -> list[DashboardDailyUsage]:
    """LLM 사용량 행을 UTC 날짜별로 합산한다."""

    grouped: dict[date, dict[str, int]] = defaultdict(
        lambda: {
            "request_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
    )
    for row in rows:
        used_at = _timestamp_value(row, "used_at")
        if used_at is None:
            continue
        bucket = grouped[used_at.date()]
        bucket["request_count"] += 1
        bucket["input_tokens"] += _int_value(row, "input_tokens")
        bucket["output_tokens"] += _int_value(row, "output_tokens")
        bucket["total_tokens"] += _int_value(row, "total_tokens")

    return [
        DashboardDailyUsage(date=day, **grouped[day])
        for day in sorted(grouped)
    ]


def _provider_usage(rows: Iterable[Row]) -> list[DashboardProviderUsage]:
    """LLM 사용량을 provider와 model 조합별로 합산한다."""

    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {
            "request_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
    )
    for row in rows:
        key = (_text_value(row, "provider"), _text_value(row, "model_name"))
        bucket = grouped[key]
        bucket["request_count"] += 1
        bucket["input_tokens"] += _int_value(row, "input_tokens")
        bucket["output_tokens"] += _int_value(row, "output_tokens")
        bucket["total_tokens"] += _int_value(row, "total_tokens")

    total_tokens = sum(bucket["total_tokens"] for bucket in grouped.values())
    ordered = sorted(
        grouped.items(),
        key=lambda item: (-item[1]["total_tokens"], item[0][0], item[0][1]),
    )
    return [
        DashboardProviderUsage(
            provider=provider,
            model_name=model_name,
            token_share=(
                round(bucket["total_tokens"] / total_tokens, 4)
                if total_tokens
                else 0.0
            ),
            **bucket,
        )
        for (provider, model_name), bucket in ordered
    ]


def _usage_success(row: Row) -> bool | None:
    """finish_reason이 관측된 경우에만 AI 요청 성공 여부를 판정한다."""

    reason = _optional_text_value(row, "finish_reason")
    if not reason:
        return None
    normalized = reason.lower()
    failed = ("error", "failed", "failure", "cancelled", "canceled", "timeout")
    return not any(word in normalized for word in failed)


def _usage_quality(rows: Iterable[Row]) -> dict[str, float | int | None]:
    """LLM finish_reason과 provider_latency에서 품질 KPI를 계산한다."""

    observed = 0
    error_count = 0
    latencies: list[float] = []
    for row in rows:
        success = _usage_success(row)
        if success is not None:
            observed += 1
            if not success:
                error_count += 1
        raw_latency = row.get("provider_latency")
        try:
            if raw_latency is not None:
                latency = float(raw_latency)
                if latency >= 0:
                    latencies.append(latency)
        except (TypeError, ValueError):
            continue

    latencies.sort()
    p95_index = max(ceil(len(latencies) * 0.95) - 1, 0)
    return {
        "error_count": error_count,
        "error_rate": (error_count / observed if observed else None),
        "average_latency_ms": (
            round(sum(latencies) / len(latencies), 2) if latencies else None
        ),
        "p95_latency_ms": round(latencies[p95_index], 2) if latencies else None,
    }


def _usage_details(
    rows: Iterable[Row],
    *,
    user_labels: Mapping[str, str] | None = None,
) -> list[DashboardUsageDetail]:
    """llm_usage 원본 행을 AI 사용량 상세 DTO로 변환한다."""

    labels = user_labels or {}
    details: list[DashboardUsageDetail] = []
    for row in rows:
        user_id = _optional_text_value(row, "user_id")
        details.append(
            DashboardUsageDetail(
                id=_optional_text_value(row, "id"),
                user_id=user_id,
                user_label=labels.get(user_id, user_id) if user_id else None,
                provider=_text_value(row, "provider"),
                model_name=_text_value(row, "model_name"),
                input_tokens=_int_value(row, "input_tokens"),
                output_tokens=_int_value(row, "output_tokens"),
                total_tokens=_int_value(row, "total_tokens"),
                used_at=_timestamp_value(row, "used_at"),
                finish_reason=_optional_text_value(row, "finish_reason"),
                provider_latency=(
                    _int_value(row, "provider_latency")
                    if row.get("provider_latency") is not None
                    else None
                ),
                success=_usage_success(row),
            )
        )
    return sorted(
        details,
        key=lambda item: item.used_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


def _api_rows_with_timestamps(rows: Iterable[Row]) -> list[tuple[Row, datetime]]:
    """유효한 요청 시각이 있는 API 로그만 정렬 가능한 형태로 만든다."""

    with_timestamps = []
    for row in rows:
        requested_at = _timestamp_value(row, "requested_at")
        if requested_at is not None:
            with_timestamps.append((row, requested_at))
    return with_timestamps


def _recent_api_calls(
    rows: Iterable[Row],
    *,
    limit: int,
    user_labels: Mapping[str, str] | None = None,
) -> list[DashboardRecentApiCall]:
    """API 로그에서 민감한 본문 없이 최근 호출 목록을 만든다."""

    ordered = sorted(
        _api_rows_with_timestamps(rows),
        key=lambda item: item[1],
        reverse=True,
    )[:limit]
    labels = user_labels or {}
    calls = []
    for row, requested_at in ordered:
        status_code = _int_value(row, "status_code")
        if not 100 <= status_code <= 599:
            continue
        calls.append(
            DashboardRecentApiCall(
                api_name=_text_value(row, "api_name"),
                requested_at=requested_at,
                response_time_ms=_int_value(row, "response_time_ms"),
                status_code=status_code,
                success=_bool_value(row, "success"),
                id=_optional_text_value(row, "id"),
                user_id=_optional_text_value(row, "user_id"),
                user_label=(
                    labels.get(_optional_text_value(row, "user_id"), _optional_text_value(row, "user_id"))
                    if _optional_text_value(row, "user_id")
                    else None
                ),
            )
        )
    return calls


def _api_summary(rows: Iterable[Row]) -> DashboardApiSummary:
    """API 로그의 성공률·응답 시간 요약을 계산한다."""

    rows = list(rows)
    success_count = sum(1 for row in rows if _bool_value(row, "success"))
    response_times = [_int_value(row, "response_time_ms") for row in rows]
    response_times.sort()
    request_count = len(rows)
    p95_index = max(ceil(len(response_times) * 0.95) - 1, 0)
    return DashboardApiSummary(
        request_count=request_count,
        success_count=success_count,
        failure_count=request_count - success_count,
        success_rate=_success_rate(success_count, request_count),
        average_response_time_ms=(
            round(sum(response_times) / request_count, 2)
            if request_count
            else 0.0
        ),
        p95_response_time_ms=response_times[p95_index] if response_times else 0,
    )


def _endpoint_usage(rows: Iterable[Row]) -> list[DashboardEndpointUsage]:
    """API 로그를 endpoint별 호출량과 응답 시간으로 합산한다."""

    grouped: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[_text_value(row, "api_name")].append(row)

    result = []
    for api_name, endpoint_rows in grouped.items():
        request_count = len(endpoint_rows)
        success_count = sum(
            1 for row in endpoint_rows if _bool_value(row, "success")
        )
        response_times = [
            _int_value(row, "response_time_ms") for row in endpoint_rows
        ]
        response_times.sort()
        p95_index = max(ceil(len(response_times) * 0.95) - 1, 0)
        result.append(
            DashboardEndpointUsage(
                api_name=api_name,
                request_count=request_count,
                success_count=success_count,
                failure_count=request_count - success_count,
                success_rate=_success_rate(success_count, request_count),
                average_response_time_ms=round(
                    sum(response_times) / request_count, 2
                ),
                p95_response_time_ms=(
                    response_times[p95_index] if response_times else 0
                ),
            )
        )
    return sorted(result, key=lambda item: (-item.request_count, item.api_name))


def _status_code_usage(rows: Iterable[Row]) -> list[DashboardStatusCodeUsage]:
    """API 로그를 HTTP 상태 코드별 요청 수로 집계한다."""

    grouped: dict[int, list[Row]] = defaultdict(list)
    for row in rows:
        status_code = _int_value(row, "status_code")
        if 100 <= status_code <= 599:
            grouped[status_code].append(row)
    result: list[DashboardStatusCodeUsage] = []
    for status_code, status_rows in grouped.items():
        success_count = sum(
            1 for row in status_rows if _bool_value(row, "success")
        )
        result.append(
            DashboardStatusCodeUsage(
                status_code=status_code,
                request_count=len(status_rows),
                success_count=success_count,
                failure_count=len(status_rows) - success_count,
            )
        )
    return sorted(result, key=lambda item: item.status_code)


def build_overview(
    llm_rows: list[Row],
    api_rows: list[Row],
    *,
    days: int,
    from_at: datetime,
    to_at: datetime,
    recent_limit: int,
    user_rows: Iterable[Row] = (),
    user_id: str | None = None,
    model_name: str | None = None,
    api_name: str | None = None,
) -> DashboardOverviewResponse:
    """두 테이블을 합쳐 Dashboard Home 응답을 생성한다."""

    filtered_llm_rows = _filtered_rows(
        llm_rows,
        user_id=user_id,
        model_name=model_name,
    )
    filtered_api_rows = _filtered_rows(
        api_rows,
        user_id=user_id,
        api_name=api_name,
    )
    user_rows = list(user_rows)
    labels = _user_labels(user_rows)
    user_ids = {
        str(row["user_id"])
        for row in [*filtered_llm_rows, *filtered_api_rows]
        if row.get("user_id") is not None
    }
    api_summary = _api_summary(filtered_api_rows)
    return DashboardOverviewResponse(
        period=_period(days, from_at, to_at),
        tracked_user_count=len(user_ids),
        registered_user_count=_registered_user_count(
            user_rows,
            from_at=from_at,
            to_at=to_at,
        ),
        ai_call_count=len(filtered_llm_rows),
        api_request_count=len(filtered_api_rows),
        total_tokens=sum(_int_value(row, "total_tokens") for row in filtered_llm_rows),
        api_success_rate=api_summary.success_rate,
        average_response_time_ms=api_summary.average_response_time_ms,
        daily_ai_usage=_daily_usage(filtered_llm_rows),
        recent_activity=[
            DashboardRecentActivity(
                api_name=call.api_name,
                requested_at=call.requested_at,
                response_time_ms=call.response_time_ms,
                status_code=call.status_code,
                success=call.success,
                user_id=call.user_id,
                user_label=call.user_label,
            )
            for call in _recent_api_calls(
                filtered_api_rows,
                limit=recent_limit,
                user_labels=labels,
            )
        ],
        recent_ai_activity=_usage_details(
            filtered_llm_rows,
            user_labels=labels,
        )[:recent_limit],
        users=_dashboard_users(user_rows),
    )


def build_usage(
    rows: list[Row],
    *,
    days: int,
    from_at: datetime,
    to_at: datetime,
    user_rows: Iterable[Row] = (),
    user_id: str | None = None,
    model_name: str | None = None,
) -> DashboardUsageResponse:
    """``llm_usage`` 행을 AI 사용량 화면 응답으로 변환한다."""

    rows = _filtered_rows(rows, user_id=user_id, model_name=model_name)
    input_tokens = sum(_int_value(row, "input_tokens") for row in rows)
    output_tokens = sum(_int_value(row, "output_tokens") for row in rows)
    total_tokens = sum(_int_value(row, "total_tokens") for row in rows)
    request_count = len(rows)
    quality = _usage_quality(rows)
    user_rows = list(user_rows)
    labels = _user_labels(user_rows)
    return DashboardUsageResponse(
        period=_period(days, from_at, to_at),
        summary=DashboardUsageSummary(
            request_count=request_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            average_tokens_per_request=(
                round(total_tokens / request_count, 2)
                if request_count
                else 0.0
            ),
            **quality,
        ),
        providers=_provider_usage(rows),
        daily_usage=_daily_usage(rows),
        details=_usage_details(rows, user_labels=labels),
    )


def build_api_calls(
    rows: list[Row],
    *,
    days: int,
    from_at: datetime,
    to_at: datetime,
    recent_limit: int,
    user_rows: Iterable[Row] = (),
    user_id: str | None = None,
    api_name: str | None = None,
) -> DashboardApiCallsResponse:
    """``api_logs`` 행을 API 호출 화면 응답으로 변환한다."""

    rows = _filtered_rows(rows, user_id=user_id, api_name=api_name)
    user_rows = list(user_rows)
    labels = _user_labels(user_rows)
    all_calls = _recent_api_calls(
        rows,
        limit=len(rows),
        user_labels=labels,
    )
    return DashboardApiCallsResponse(
        period=_period(days, from_at, to_at),
        summary=_api_summary(rows),
        endpoints=_endpoint_usage(rows),
        recent_calls=all_calls[:recent_limit],
        all_calls=all_calls,
        status_codes=_status_code_usage(rows),
    )


__all__ = ["build_api_calls", "build_overview", "build_usage"]
