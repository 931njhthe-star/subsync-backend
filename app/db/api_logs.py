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

    async def list_recent(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, object]]:
        """대시보드 집계에 필요한 기간 내 ``api_logs`` 행을 조회한다.

        요청·응답 본문과 오류 원문은 개인정보·자막이 포함될 수 있어 조회하지
        않는다. 대시보드에는 endpoint, 상태 코드, 성공 여부, 처리 시간만 제공한다.

        Args:
            since: ``requested_at`` 기준으로 포함할 시작 시각(UTC).
            limit: 한 번에 읽을 최대 행 수. 대시보드용 안전 상한은 10,000건이다.

        Returns:
            API 호출 집계에 사용할 Supabase 행 목록.
        """

        if not self.is_configured:
            return []

        safe_limit = min(max(limit, 1), 50_000)
        page_size = min(safe_limit, 1_000)
        selected_columns = (
            "id,api_name,user_id,requested_at,response_time_ms,status_code,success"
        )
        rows: list[dict[str, object]] = []
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            offset = 0
            while len(rows) < safe_limit:
                current_limit = min(page_size, safe_limit - len(rows))
                params: list[tuple[str, str]] = [
                    ("select", selected_columns),
                    ("requested_at", f"gte.{since.astimezone(timezone.utc).isoformat()}"),
                    ("order", "requested_at.desc"),
                    ("limit", str(current_limit)),
                    ("offset", str(offset)),
                ]
                if until is not None:
                    params.append(
                        (
                            "requested_at",
                            f"lt.{until.astimezone(timezone.utc).isoformat()}",
                        )
                    )
                response = await client.get(
                    f"{self._url}/rest/v1/api_logs",
                    headers={
                        "apikey": self._secret_key,
                        "Authorization": f"Bearer {self._secret_key}",
                        "Content-Type": "application/json",
                    },
                    params=params,
                )
                response.raise_for_status()
                page = response.json()
                if not isinstance(page, list):
                    raise ValueError("Supabase api_logs 응답 형식이 올바르지 않습니다.")
                valid_page = [row for row in page if isinstance(row, dict)]
                rows.extend(valid_page)
                if len(valid_page) < current_limit:
                    break
                offset += len(valid_page)
        return rows[:safe_limit]
