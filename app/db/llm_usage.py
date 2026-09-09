"""Supabase ``llm_usage`` 테이블에 Tutor 토큰 사용량을 기록·조회한다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class LLMUsageEntry:
    """한 번의 Tutor provider 호출에서 발생한 토큰 사용량.

    현재 Tutor 라우터는 인증 연동 전이라 ``user_id``를 저장하지 않는다. 테이블에
    user_id가 이미 기록된 운영 행이 있으면 Dashboard API가 그 값을 기준으로
    사용자별이 아닌 전체 고유 사용자 수를 집계할 수 있다.
    """

    provider: str
    model_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    finish_reason: str | None = None  # stop: 모델이 자연스럽게 답변을 끝냄 / length: 최대 출력 토큰에 도달해 답변이 잘림  / content_filter 또는 safety: 안전 정책에 따라 생성이 중단됨
    provider_latency: int | None = None


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

    async def list_recent(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, object]]:
        """대시보드 집계에 필요한 기간 내 ``llm_usage`` 행을 조회한다.

        Args:
            since: ``used_at`` 기준으로 포함할 시작 시각(UTC).
            limit: 한 번에 읽을 최대 행 수. 대시보드용 안전 상한은 10,000건이다.

        Returns:
            provider, model, token, 시각, 사용자 식별자를 담은 Supabase 행 목록.

        Note:
            현재 부트캠프 규모에서는 애플리케이션에서 집계한다. 데이터가 크게
            늘어나면 동일 집계를 Supabase view/RPC로 옮겨 응답 크기를 줄인다.
        """

        if not self.is_configured:
            return []

        safe_limit = min(max(limit, 1), 50_000)
        page_size = min(safe_limit, 1_000)
        selected_columns = (
            "id,provider,model_name,input_tokens,output_tokens,total_tokens,"
            "used_at,user_id,finish_reason,provider_latency"
        )
        rows: list[dict[str, object]] = []
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            offset = 0
            while len(rows) < safe_limit:
                current_limit = min(page_size, safe_limit - len(rows))
                params: list[tuple[str, str]] = [
                    ("select", selected_columns),
                    ("used_at", f"gte.{since.astimezone(timezone.utc).isoformat()}"),
                    ("order", "used_at.desc"),
                    ("limit", str(current_limit)),
                    ("offset", str(offset)),
                ]
                if until is not None:
                    params.append(
                        ("used_at", f"lt.{until.astimezone(timezone.utc).isoformat()}")
                    )
                response = await client.get(
                    f"{self._url}/rest/v1/llm_usage",
                    headers=self._headers(),
                    params=params,
                )
                response.raise_for_status()
                page = response.json()
                if not isinstance(page, list):
                    raise ValueError("Supabase llm_usage 응답 형식이 올바르지 않습니다.")
                valid_page = [row for row in page if isinstance(row, dict)]
                rows.extend(valid_page)
                if len(valid_page) < current_limit:
                    break
                offset += len(valid_page)
        return rows[:safe_limit]


__all__ = ["LLMUsageEntry", "LLMUsageRepository", "LLMUsageSummary"]
