"""Supabase ``public.login_history``에 로그인·로그아웃 시각을 기록한다."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx


class LoginHistoryRepository:
    """서버 전용 키로 로그인 이력을 추가하거나 종료한다."""

    def __init__(self, *, url: str, secret_key: str, timeout_seconds: float = 2.0) -> None:
        """Supabase REST 주소와 서버 전용 키를 설정한다."""

        self._url = url.rstrip("/")
        self._secret_key = secret_key
        self._timeout_seconds = max(timeout_seconds, 0.1)

    @property
    def is_configured(self) -> bool:
        """이력 테이블에 안전하게 요청할 최소 설정이 있는지 반환한다."""

        return bool(self._url and self._secret_key)

    def _headers(self, *, prefer: str) -> dict[str, str]:
        """REST 요청 공통 헤더를 만든다."""

        return {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }

    def login_row(self, user_id: str) -> dict[str, object]:
        """``/me`` 성공 시 INSERT할 컬럼을 만든다.

        ``last_access_at``은 매 API마다 올리지 않고, 로그인 시점과 같게 한 번만 넣는다.
        """

        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": str(uuid4()),
            "user_id": user_id,
            "login_at": now,
            "logout_at": None,
            "last_access_at": now,
        }

    async def record_login(self, user_id: str) -> dict[str, object]:
        """열린 로그인 세션 한 줄을 추가한다."""

        if not self.is_configured:
            raise RuntimeError("Supabase 로그인 이력 저장소가 설정되지 않았습니다.")
        row = self.login_row(user_id)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._url}/rest/v1/login_history",
                headers=self._headers(prefer="return=minimal"),
                json=row,
            )
        response.raise_for_status()
        return row

    async def record_logout(self, user_id: str) -> None:
        """아직 로그아웃되지 않은 이력에 ``logout_at``을 채운다."""

        if not self.is_configured:
            raise RuntimeError("Supabase 로그인 이력 저장소가 설정되지 않았습니다.")
        now = datetime.now(timezone.utc).isoformat()
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.patch(
                f"{self._url}/rest/v1/login_history",
                headers=self._headers(prefer="return=minimal"),
                params={
                    "user_id": f"eq.{user_id}",
                    "logout_at": "is.null",
                },
                json={"logout_at": now, "last_access_at": now},
            )
        response.raise_for_status()
