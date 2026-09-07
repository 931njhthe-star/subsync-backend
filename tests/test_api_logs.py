"""익명 API 로그의 Supabase 저장과 실패 격리를 검증한다."""

import asyncio
from uuid import UUID

from fastapi.testclient import TestClient

import app.main as main_module
from app.db.api_logs import ApiLogEntry, ApiLogRepository


client = TestClient(main_module.app)


def test_api_log_entry_keeps_anonymous_requests_free_of_user_data():
    """로그 행에는 user_id와 요청 본문을 넣지 않는지 확인한다."""

    row = ApiLogEntry(
        api_name="POST /api/v1/tutor/ask",
        response_time_ms=42,
        status_code=200,
        success=True,
    ).as_row()

    UUID(str(row["id"]))
    assert row["user_id"] is None
    assert row["api_name"] == "POST /api/v1/tutor/ask"
    assert "user_message" not in row


def test_api_log_repository_posts_the_current_table_shape(monkeypatch):
    """repository가 Supabase REST에 api_logs 컬럼만 보내는지 확인한다."""

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, headers, json):
            captured.update(url=url, headers=headers, json=json)
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    repository = ApiLogRepository(
        url="https://example.supabase.co",
        secret_key="server-key",
    )
    asyncio.run(
        repository.write(
            ApiLogEntry(
                api_name="POST /api/v1/tutor/ask",
                response_time_ms=12,
                status_code=200,
                success=True,
            )
        )
    )

    assert captured["url"] == "https://example.supabase.co/rest/v1/api_logs"
    assert captured["headers"]["Prefer"] == "return=minimal"
    assert captured["json"]["user_id"] is None


def test_api_request_is_logged_without_blocking_a_successful_response(monkeypatch):
    """Supabase 로그 저장은 API 응답과 별개로 실행되는지 확인한다."""

    entries: list[ApiLogEntry] = []

    class RecordingRepository:
        async def write(self, entry: ApiLogEntry) -> None:
            entries.append(entry)

    monkeypatch.setattr(main_module, "api_log_repository", RecordingRepository())
    response = client.post(
        "/api/v1/tutor/proactive",
        json={
            "video_id": "log-video",
            "timestamp": 1,
            "recent_subtitles": [{"time": 1, "en": "A representation helps."}],
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert len(entries) == 1
    assert entries[0].api_name == "POST /api/v1/tutor/proactive"
    assert entries[0].status_code == 200
    assert entries[0].success is True


def test_api_log_failure_does_not_change_the_original_response(monkeypatch):
    """Supabase 장애가 Tutor API의 성공 응답을 실패로 바꾸지 않는지 확인한다."""

    class FailingRepository:
        async def write(self, entry: ApiLogEntry) -> None:
            raise RuntimeError("Supabase unavailable")

    monkeypatch.setattr(main_module, "api_log_repository", FailingRepository())
    response = client.post(
        "/api/v1/tutor/proactive",
        json={
            "video_id": "log-failure-video",
            "timestamp": 1,
            "recent_subtitles": [{"time": 1, "en": "A representation helps."}],
        },
    )

    assert response.status_code == 200


def test_unknown_frontend_event_endpoint_is_not_saved_as_an_api_log(monkeypatch):
    """폐기된 client event 요청이 운영 API 로그를 오염시키지 않는지 확인한다."""

    entries: list[ApiLogEntry] = []

    class RecordingRepository:
        async def write(self, entry: ApiLogEntry) -> None:
            entries.append(entry)

    monkeypatch.setattr(main_module, "api_log_repository", RecordingRepository())
    response = client.post("/api/v1/logs/event", json={"event": "playback"})

    assert response.status_code == 404
    assert entries == []
