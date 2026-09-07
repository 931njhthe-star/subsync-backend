"""Supabase ``api_logs`` 테이블에 익명 운영 로그를 기록한다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class ApiLogEntry:
    """요청 본문 없이 저장하는 API 처리 결과."""

    api_name: str
    response_time_ms: int
    status_code: int
    success: bool
    error_message: str | None = None

    def as_row(self) -> dict[str, object]:
        """현재 ``public.api_logs`` 컬럼 이름에 맞는 INSERT 행을 만든다."""

        return {
            "id": str(uuid4()),
            "user_id": None,
            "requested_at": datetime.now(timezone.utc).isoformat(),
            **asdict(self),
        }


class ApiLogRepository:
    """Supabase REST API를 사용하는 ``api_logs`` 전용 저장소.

    URL 또는 서버 전용 키가 없으면 로컬 개발을 위해 아무 작업도 하지 않는다.
    로그 저장 실패는 원래 API 요청의 성공 여부에 영향을 주지 않도록 호출자가
    ``write_safely``를 사용한다.
    """

    def __init__(self, *, url: str, secret_key: str, timeout_seconds: float = 2.0) -> None:
        """Supabase REST 주소와 서버 전용 키를 설정한다."""

        self._url = url.rstrip("/")
        self._secret_key = secret_key
        self._timeout_seconds = max(timeout_seconds, 0.1)

    @property
    def is_configured(self) -> bool:
        """Supabase에 안전하게 INSERT할 최소 설정이 있는지 반환한다."""

        return bool(self._url and self._secret_key)

    async def write(self, entry: ApiLogEntry) -> None:
        """로그 한 건을 기록한다. 미설정 환경에서는 아무 작업도 하지 않는다."""

        if not self.is_configured:
            return

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._url}/rest/v1/api_logs",
                headers={
                    "apikey": self._secret_key,
                    "Authorization": f"Bearer {self._secret_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json=entry.as_row(),
            )
        response.raise_for_status()
