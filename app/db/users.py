"""Supabase ``public.users``에 Auth 사용자를 동기화한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.security import AuthUser


@dataclass(frozen=True)
class UserRow:
    """``public.users`` 한 행."""

    id: str
    google_account_id: str | None
    email: str | None
    created_at: str
    last_login_at: str


class UserRepository:
    """서버 전용 키로 ``users``를 조회·삽입·갱신한다.

    ``id``는 항상 ``auth.users.id``와 같게 둔다. 새 UUID를 만들지 않는다.
    """

    def __init__(self, *, url: str, secret_key: str, timeout_seconds: float = 2.0) -> None:
        """Supabase REST 주소와 서버 전용 키를 설정한다."""

        self._url = url.rstrip("/")
        self._secret_key = secret_key
        self._timeout_seconds = max(timeout_seconds, 0.1)

    @property
    def is_configured(self) -> bool:
        """사용자 테이블에 안전하게 요청할 최소 설정이 있는지 반환한다."""

        return bool(self._url and self._secret_key)

    def _headers(self, *, prefer: str) -> dict[str, str]:
        """REST 요청 공통 헤더를 만든다."""

        return {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }

    async def upsert_from_auth(self, auth_user: AuthUser) -> UserRow:
        """로그인 시 ``users``를 만들거나 ``last_login_at``을 갱신한다.

        이미 있는 행의 ``created_at``은 덮어쓰지 않는다. ``created_at``이 NOT NULL
        이므로 신규 insert에만 현재 시각을 넣는다.
        """

        if not self.is_configured:
            raise RuntimeError("Supabase 사용자 저장소가 설정되지 않았습니다.")

        now = datetime.now(timezone.utc).isoformat()
        existing = await self._get(auth_user.id)
        if existing is None:
            row = {
                "id": auth_user.id,
                "google_account_id": auth_user.google_account_id,
                "email": auth_user.email,
                "created_at": now,
                "last_login_at": now,
            }
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._url}/rest/v1/users",
                    headers=self._headers(prefer="return=representation"),
                    json=row,
                )
            response.raise_for_status()
            return _row_from_response(response.json(), fallback=row)

        patch = {
            "google_account_id": auth_user.google_account_id,
            "email": auth_user.email,
            "last_login_at": now,
        }
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.patch(
                f"{self._url}/rest/v1/users",
                headers=self._headers(prefer="return=representation"),
                params={"id": f"eq.{auth_user.id}"},
                json=patch,
            )
        response.raise_for_status()
        return _row_from_response(
            response.json(),
            fallback={**existing.__dict__, **patch},
        )

    async def _get(self, user_id: str) -> UserRow | None:
        """기본키로 기존 앱 사용자를 찾는다."""

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(
                f"{self._url}/rest/v1/users",
                headers=self._headers(prefer="return=representation"),
                params={"id": f"eq.{user_id}", "select": "*", "limit": "1"},
            )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            return None
        first = rows[0]
        if not isinstance(first, dict):
            return None
        return UserRow(
            id=str(first.get("id") or user_id),
            google_account_id=_optional_text(first.get("google_account_id")),
            email=_optional_text(first.get("email")),
            created_at=str(first.get("created_at") or ""),
            last_login_at=str(first.get("last_login_at") or ""),
        )

    async def list_directory(self, *, limit: int = 50_000) -> list[dict[str, object]]:
        """관리자 대시보드에서 사용할 사용자 ID·이메일 목록을 조회한다."""

        if not self.is_configured:
            return []

        safe_limit = min(max(limit, 1), 50_000)
        page_size = min(safe_limit, 1_000)
        rows: list[dict[str, object]] = []
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            offset = 0
            while len(rows) < safe_limit:
                current_limit = min(page_size, safe_limit - len(rows))
                response = await client.get(
                    f"{self._url}/rest/v1/users",
                    headers=self._headers(prefer="return=representation"),
                    params={
                        "select": "id,email,google_account_id,created_at,last_login_at",
                        "order": "id.asc",
                        "limit": str(current_limit),
                        "offset": str(offset),
                    },
                )
                response.raise_for_status()
                page = response.json()
                if not isinstance(page, list):
                    raise ValueError("Supabase users 응답 형식이 올바르지 않습니다.")
                valid_page = [row for row in page if isinstance(row, dict)]
                rows.extend(valid_page)
                if len(valid_page) < current_limit:
                    break
                offset += len(valid_page)
        return rows[:safe_limit]


def _optional_text(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _row_from_response(body: object, *, fallback: dict[str, object]) -> UserRow:
    """representation 응답이 리스트/객체 어느 쪽이든 한 행으로 맞춘다."""

    source = fallback
    if isinstance(body, list) and body and isinstance(body[0], dict):
        source = {**fallback, **body[0]}
    elif isinstance(body, dict):
        source = {**fallback, **body}
    return UserRow(
        id=str(source.get("id") or ""),
        google_account_id=_optional_text(source.get("google_account_id")),
        email=_optional_text(source.get("email")),
        created_at=str(source.get("created_at") or ""),
        last_login_at=str(source.get("last_login_at") or ""),
    )
