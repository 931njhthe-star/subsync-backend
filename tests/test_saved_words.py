"""저장 단어의 정규화·Supabase REST 요청·API 계약을 검증한다."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

import app.main as main_module
from app.api.deps import get_saved_words_user_id
from app.api.v1.words import get_saved_word_service
from app.db.saved_words import SavedWordRecord, SavedWordsRepository
from app.services.word_service import SavedWordService, normalize_saved_word


client = TestClient(main_module.app)
TEST_USER_ID = UUID("11111111-1111-1111-1111-111111111111")
TEST_WORD_ID = UUID("22222222-2222-2222-2222-222222222222")
SAVED_AT = datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc)


def test_normalize_saved_word_preserves_first_display_form():
    """표시용 원래 표기와 대소문자 중복 확인용 값을 분리한다."""

    assert normalize_saved_word("  Apple  ") == ("Apple", "apple")
    assert normalize_saved_word("running") == ("running", "running")


def test_saved_words_repository_sends_upsert_request(monkeypatch):
    """repository가 user_id와 word_lower를 포함한 upsert 요청을 보낸다."""

    captured: dict[str, Any] = {}
    response_row = {
        "id": str(TEST_WORD_ID),
        "user_id": str(TEST_USER_ID),
        "word": "Apple",
        "word_lower": "apple",
        "saved_at": SAVED_AT.isoformat(),
    }

    class FakeResponse:
        status_code = 201

        def json(self):
            return [response_row]

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def request(self, method, url, *, headers, params, json):
            captured.update(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
            )
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    repository = SavedWordsRepository(
        url="https://example.supabase.co",
        secret_key="server-key",
    )

    record, created = asyncio.run(
        repository.save(
            user_id=TEST_USER_ID,
            word="Apple",
            word_lower="apple",
        )
    )

    assert created is True
    assert record.word == "Apple"
    assert captured["method"] == "POST"
    assert captured["url"] == (
        "https://example.supabase.co/rest/v1/saved_words"
    )
    assert captured["params"]["on_conflict"] == "user_id,word_lower"
    assert captured["headers"]["Prefer"] == (
        "resolution=ignore-duplicates,return=representation"
    )
    assert captured["json"]["user_id"] == str(TEST_USER_ID)
    assert captured["json"]["word_lower"] == "apple"


def test_saved_words_repository_lists_and_deletes_by_user_and_id(monkeypatch):
    """조회·삭제 요청이 사용자와 단어 ID 조건을 함께 사용하는지 확인한다."""

    captured: list[dict[str, Any]] = []
    response_row = {
        "id": str(TEST_WORD_ID),
        "user_id": str(TEST_USER_ID),
        "word": "Apple",
        "word_lower": "apple",
        "saved_at": SAVED_AT.isoformat(),
    }

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def request(self, method, url, *, headers, params, json):
            captured.append(
                {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "params": params,
                    "json": json,
                }
            )
            payload = [response_row] if method == "GET" else [{"id": str(TEST_WORD_ID)}]
            return FakeResponse(payload)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    repository = SavedWordsRepository(
        url="https://example.supabase.co",
        secret_key="server-key",
    )

    records = asyncio.run(
        repository.list_for_user(user_id=TEST_USER_ID, limit=10)
    )
    asyncio.run(
        repository.delete_for_user(
            user_id=TEST_USER_ID,
            word_id=TEST_WORD_ID,
        )
    )

    assert records[0].word == "Apple"
    assert captured[0]["method"] == "GET"
    assert captured[0]["params"]["user_id"] == f"eq.{TEST_USER_ID}"
    assert captured[0]["params"]["limit"] == "10"
    assert captured[1]["method"] == "DELETE"
    assert captured[1]["params"]["id"] == f"eq.{TEST_WORD_ID}"
    assert captured[1]["params"]["user_id"] == f"eq.{TEST_USER_ID}"
    assert captured[1]["headers"]["Prefer"] == "return=representation"


class FakeSavedWordService:
    """라우터 테스트에서 Supabase 대신 고정된 저장 단어를 제공한다."""

    def __init__(self) -> None:
        self.record = SavedWordRecord(
            id=TEST_WORD_ID,
            user_id=TEST_USER_ID,
            word="Apple",
            word_lower="apple",
            saved_at=SAVED_AT,
        )
        self.created = True

    async def save_word(self, *, user_id: UUID, word: str):
        assert user_id == TEST_USER_ID
        record = self.record
        created = self.created
        self.created = False
        return record, created

    async def list_words(self, *, user_id: UUID, limit: int):
        assert user_id == TEST_USER_ID
        assert limit == 100
        return [self.record]

    async def delete_word(self, *, user_id: UUID, word_id: UUID):
        assert user_id == TEST_USER_ID
        assert word_id == TEST_WORD_ID


def test_saved_words_routes_save_list_and_delete_without_oauth():
    """OAuth 전 개발 단계에서도 임시 사용자 header로 API 계약을 확인한다."""

    fake_service = FakeSavedWordService()
    main_module.app.dependency_overrides[get_saved_words_user_id] = (
        lambda: TEST_USER_ID
    )
    main_module.app.dependency_overrides[get_saved_word_service] = (
        lambda: fake_service
    )
    try:
        first_save = client.post(
            "/api/v1/words",
            json={"word": "Apple"},
        )
        duplicate_save = client.post(
            "/api/v1/words",
            json={"word": "apple"},
        )
        listed = client.get("/api/v1/words")
        deleted = client.delete(f"/api/v1/words/{TEST_WORD_ID}")
    finally:
        main_module.app.dependency_overrides.clear()

    assert first_save.status_code == 201
    assert first_save.json()["word"] == "Apple"
    assert duplicate_save.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["word_lower"] == "apple"
    assert deleted.status_code == 204


def test_saved_words_routes_require_development_user_header_before_oauth():
    """OAuth 전에는 사용자 식별 header가 없으면 저장 단어 API를 거부한다."""

    response = client.get("/api/v1/words")

    assert response.status_code == 401
