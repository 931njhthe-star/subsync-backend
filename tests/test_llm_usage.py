"""Tutor 토큰 사용량의 Supabase 저장·조회 계약을 검증한다."""

import asyncio

import httpx

from app.db.llm_usage import LLMUsageEntry, LLMUsageRepository


def test_usage_entry_matches_current_table_without_user_identifier():
    """로그인 전 요청은 현재 DB 테이블 컬럼에 맞춰 사용량만 저장한다."""

    row = LLMUsageEntry(
        provider="groq",
        model_name="openai/gpt-oss-20b",
        input_tokens=120,
        output_tokens=30,
        total_tokens=150,
        finish_reason="stop",
        provider_latency=247,
    ).as_row()

    assert "user_id" not in row
    assert row["total_tokens"] == 150
    assert row["finish_reason"] == "stop"
    assert row["provider_latency"] == 247


def test_usage_repository_posts_and_summarizes_all_rows(monkeypatch):
    """REST 저장 행과 전체 개발 사용량 합계의 DB 계약을 고정한다."""

    captured: dict[str, object] = {}

    class FakeResponse:
        def __init__(self, rows=None):
            self._rows = rows or []

        def raise_for_status(self):
            return None

        def json(self):
            return self._rows

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, *, headers, json):
            captured["post"] = {"url": url, "headers": headers, "json": json}
            return FakeResponse()

        async def get(self, url, *, headers, params):
            captured["get"] = {"url": url, "headers": headers, "params": params}
            return FakeResponse(
                [
                    {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
                    {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
                ]
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    repository = LLMUsageRepository(
        url="https://example.supabase.co",
        secret_key="server-key",
    )
    asyncio.run(
        repository.write(
            LLMUsageEntry("groq", "model", 120, 30, 150, "stop", 247)
        )
    )
    summary = asyncio.run(repository.summarize_all())

    assert captured["post"]["url"] == "https://example.supabase.co/rest/v1/llm_usage"
    assert "user_id" not in captured["post"]["json"]
    assert captured["post"]["json"]["finish_reason"] == "stop"
    assert captured["post"]["json"]["provider_latency"] == 247
    assert "user_id" not in captured["get"]["params"]
    assert summary.request_count == 2
    assert summary.input_tokens == 200
    assert summary.output_tokens == 50
    assert summary.total_tokens == 250
