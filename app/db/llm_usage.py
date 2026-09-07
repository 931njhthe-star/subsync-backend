"""Supabase ``llm_usage`` 테이블에 Tutor 토큰 사용량을 기록·조회한다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class LLMUsageEntry:
    """한 번의 Tutor provider 호출에서 발생한 토큰 사용량.

    현재 Supabase ``llm_usage`` 테이블에는 사용자 식별 컬럼이 없으므로, 개발 중에는
    모든 Tutor 호출의 provider 토큰만 기록한다. 로그인 연동 전 사용자별 집계가
    필요해지면 별도 migration으로 JWT ``sub`` 컬럼을 추가해야 한다.
    """

    provider: str
    model_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def as_row(self) -> dict[str, object]:
        """``public.llm_usage`` INSERT에 사용할 현재 시각의 행을 반환한다."""

        return {
            "id": str(uuid4()),
            "used_at": datetime.now(timezone.utc).isoformat(),
            **asdict(self),
        }


@dataclass(frozen=True)
class LLMUsageSummary:
    """현재 개발 DB에 기록된 전체 누적 토큰 사용량과 호출 횟수."""

    request_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


class LLMUsageRepository:
    """Supabase REST API로 ``llm_usage``를 비동기 저장·조회한다.

    서버 전용 키가 없으면 로컬 Tutor 실행을 막지 않기 위해 저장은 건너뛰고,
    조회는 빈 집계를 반환한다. 저장 실패는 라우터가 원래 Tutor 응답을 유지하도록
    별도 안전 래퍼에서 처리한다.
    """

    def __init__(self, *, url: str, secret_key: str, timeout_seconds: float = 2.0) -> None:
        """Supabase REST 주소와 서버 전용 키를 설정한다."""

        self._url = url.rstrip("/")
        self._secret_key = secret_key
        self._timeout_seconds = max(timeout_seconds, 0.1)

    @property
    def is_configured(self) -> bool:
        """Supabase에 안전하게 요청할 최소 설정이 있는지 반환한다."""

        return bool(self._url and self._secret_key)

    def _headers(self) -> dict[str, str]:
        """서버 전용 REST 요청에 공통으로 넣을 인증 헤더를 만든다."""

        return {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/json",
        }

    async def write(self, entry: LLMUsageEntry) -> None:
        """사용량 한 건을 저장한다. 미설정 환경에서는 아무 작업도 하지 않는다."""

        if not self.is_configured:
            return
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._url}/rest/v1/llm_usage",
                headers={**self._headers(), "Prefer": "return=minimal"},
                json=entry.as_row(),
            )
        response.raise_for_status()

    async def summarize_all(self) -> LLMUsageSummary:
        """현재 ``llm_usage`` 테이블의 전체 사용량을 합산한다."""

        empty = LLMUsageSummary(0, 0, 0, 0)
        if not self.is_configured:
            return empty
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(
                f"{self._url}/rest/v1/llm_usage",
                headers=self._headers(),
                params={
                    "select": "input_tokens,output_tokens,total_tokens",
                    "order": "used_at.desc",
                },
            )
        response.raise_for_status()
        rows = response.json()
        return LLMUsageSummary(
            request_count=len(rows),
            input_tokens=sum(max(int(row.get("input_tokens") or 0), 0) for row in rows),
            output_tokens=sum(max(int(row.get("output_tokens") or 0), 0) for row in rows),
            total_tokens=sum(max(int(row.get("total_tokens") or 0), 0) for row in rows),
        )


__all__ = ["LLMUsageEntry", "LLMUsageRepository", "LLMUsageSummary"]
