"""Streamlit 관리자 대시보드 조회 API의 집계 계약을 검증한다."""

from fastapi.testclient import TestClient

import app.main as main_module
from app.api.v1.dashboard import (
    get_dashboard_api_log_repository,
    get_dashboard_llm_usage_repository,
)


client = TestClient(main_module.app)


USAGE_ROWS = [
    {
        "provider": "gemini",
        "model_name": "gemini-3.6-flash",
        "input_tokens": 100,
        "output_tokens": 40,
        "total_tokens": 140,
        "used_at": "2026-09-08T01:00:00Z",
        "user_id": "user-001",
    },
    {
        "provider": "groq",
        "model_name": "openai/gpt-oss-20b",
        "input_tokens": 50,
        "output_tokens": 20,
        "total_tokens": 70,
        "used_at": "2026-09-07T01:00:00Z",
        "user_id": "user-002",
    },
]

API_ROWS = [
    {
        "api_name": "POST /api/v1/tutor/ask",
        "user_id": "user-001",
        "requested_at": "2026-09-08T01:02:00Z",
        "response_time_ms": 100,
        "status_code": 200,
        "success": True,
    },
    {
        "api_name": "POST /api/v1/tutor/ask",
        "user_id": "user-002",
        "requested_at": "2026-09-07T01:02:00Z",
        "response_time_ms": 300,
        "status_code": 500,
        "success": False,
    },
    {
        "api_name": "GET /api/v1/tutor/usage",
        "user_id": None,
        "requested_at": "2026-09-06T01:02:00Z",
        "response_time_ms": 200,
        "status_code": 200,
        "success": True,
    },
]


class FakeUsageRepository:
    """대시보드가 읽을 LLM usage fixture를 반환하는 fake repository."""

    async def list_recent(self, *, since, limit):
        return USAGE_ROWS


class FakeApiLogRepository:
    """대시보드가 읽을 API 로그 fixture를 반환하는 fake repository."""

    async def list_recent(self, *, since, limit):
        return API_ROWS


def _override_dashboard_repositories() -> None:
    """세 대시보드 endpoint에 공통 fixture repository를 주입한다."""

    main_module.app.dependency_overrides[get_dashboard_llm_usage_repository] = (
        lambda: FakeUsageRepository()
    )
    main_module.app.dependency_overrides[get_dashboard_api_log_repository] = (
        lambda: FakeApiLogRepository()
    )


def _clear_dashboard_overrides() -> None:
    """대시보드 전용 dependency override를 원래 상태로 되돌린다."""

    main_module.app.dependency_overrides.pop(get_dashboard_llm_usage_repository, None)
    main_module.app.dependency_overrides.pop(get_dashboard_api_log_repository, None)


def test_dashboard_overview_combines_two_tables_into_home_kpis():
    """overview가 두 테이블의 KPI·일별 AI 사용량·최근 활동을 함께 반환한다."""

    _override_dashboard_repositories()
    try:
        response = client.get(
            "/api/v1/dashboard/overview?days=7&recent_limit=2"
        )
    finally:
        _clear_dashboard_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["tracked_user_count"] == 2
    assert body["ai_call_count"] == 2
    assert body["api_request_count"] == 3
    assert body["total_tokens"] == 210
    assert body["api_success_rate"] == 0.6667
    assert body["average_response_time_ms"] == 200.0
    assert len(body["daily_ai_usage"]) == 2
    assert len(body["recent_activity"]) == 2


def test_dashboard_usage_groups_provider_and_daily_token_usage():
    """usage가 provider/model별 토큰과 날짜별 토큰을 합산한다."""

    main_module.app.dependency_overrides[get_dashboard_llm_usage_repository] = (
        lambda: FakeUsageRepository()
    )
    try:
        response = client.get("/api/v1/dashboard/usage?days=30")
    finally:
        main_module.app.dependency_overrides.pop(
            get_dashboard_llm_usage_repository, None
        )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "request_count": 2,
        "input_tokens": 150,
        "output_tokens": 60,
        "total_tokens": 210,
        "average_tokens_per_request": 105.0,
    }
    assert body["providers"][0]["provider"] == "gemini"
    assert body["providers"][0]["token_share"] == 0.6667
    assert [item["date"] for item in body["daily_usage"]] == [
        "2026-09-07",
        "2026-09-08",
    ]


def test_dashboard_api_calls_groups_endpoint_and_recent_status():
    """api-calls가 endpoint별 성공률·latency와 최근 상태 코드를 반환한다."""

    main_module.app.dependency_overrides[get_dashboard_api_log_repository] = (
        lambda: FakeApiLogRepository()
    )
    try:
        response = client.get(
            "/api/v1/dashboard/api-calls?days=7&recent_limit=2"
        )
    finally:
        main_module.app.dependency_overrides.pop(
            get_dashboard_api_log_repository, None
        )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "request_count": 3,
        "success_count": 2,
        "failure_count": 1,
        "success_rate": 0.6667,
        "average_response_time_ms": 200.0,
        "p95_response_time_ms": 300,
    }
    assert body["endpoints"][0]["api_name"] == "POST /api/v1/tutor/ask"
    assert body["endpoints"][0]["request_count"] == 2
    assert len(body["recent_calls"]) == 2
    assert body["recent_calls"][0]["status_code"] == 200


def test_dashboard_query_rejects_period_outside_supported_range():
    """대시보드 기간은 1~90일 범위만 허용한다."""

    response = client.get("/api/v1/dashboard/usage?days=0")

    assert response.status_code == 422


def test_dashboard_read_failure_returns_service_unavailable():
    """Supabase 조회 실패를 빈 성공 응답으로 숨기지 않고 503으로 반환한다."""

    class FailingRepository:
        async def list_recent(self, *, since, limit):
            raise RuntimeError("database unavailable")

    main_module.app.dependency_overrides[get_dashboard_api_log_repository] = (
        lambda: FailingRepository()
    )
    try:
        response = client.get("/api/v1/dashboard/api-calls")
    finally:
        main_module.app.dependency_overrides.pop(
            get_dashboard_api_log_repository, None
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "API 로그를 조회할 수 없습니다. 잠시 후 다시 시도해 주세요."
    }


def test_dashboard_openapi_exposes_three_read_endpoints():
    """Swagger에 이미지의 세 대시보드 화면용 조회 endpoint가 노출된다."""

    paths = app_paths = set(main_module.app.openapi()["paths"])

    assert {
        "/api/v1/dashboard/overview",
        "/api/v1/dashboard/usage",
        "/api/v1/dashboard/api-calls",
    }.issubset(paths)
