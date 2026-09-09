"""Supabase Access Token 검증.

Google 로그인 자체는 확장 프로그램이 처리한다. 백엔드는 전달받은 Bearer 토큰이
유효한지 Auth API로 확인하고, JWT의 sub를 앱 사용자 ID로 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import settings


@dataclass(frozen=True)
class AuthUser:
    """검증이 끝난 로그인 사용자.

    ``id``는 ``auth.users.id``이자 ``public.users.id``다. 비밀번호는 저장하지 않는다.
    """

    id: str
    email: str | None
    google_account_id: str | None


class AuthTokenError(Exception):
    """Access Token이 없거나 Supabase가 거부한 경우."""


def extract_google_account_id(payload: dict[str, object]) -> str | None:
    """Auth 사용자 JSON에서 Google 계정 고유 ID를 찾는다."""

    identities = payload.get("identities")
    if isinstance(identities, list):
        for identity in identities:
            if not isinstance(identity, dict):
                continue
            if str(identity.get("provider") or "") != "google":
                continue
            google_id = identity.get("id") or identity.get("identity_id")
            if google_id:
                return str(google_id)

    metadata = payload.get("user_metadata")
    if isinstance(metadata, dict):
        issuer = str(metadata.get("iss") or "")
        google_sub = metadata.get("sub") or metadata.get("provider_id")
        if google_sub and "accounts.google.com" in issuer:
            return str(google_sub)
        if google_sub and not identities:
            return str(google_sub)
    return None


def auth_user_from_payload(payload: dict[str, object]) -> AuthUser:
    """Supabase ``/auth/v1/user`` 응답을 앱 사용자로 변환한다."""

    user_id = str(payload.get("id") or "").strip()
    if not user_id:
        raise AuthTokenError("사용자 ID가 없는 세션입니다.")
    email = payload.get("email")
    return AuthUser(
        id=user_id,
        email=str(email) if email else None,
        google_account_id=extract_google_account_id(payload),
    )


async def fetch_supabase_auth_user(access_token: str) -> AuthUser:
    """Bearer Access Token을 Supabase Auth에 보내 현재 사용자를 확인한다.

    로컬 JWT 시크릿 검증 대신 Auth ``/user``를 쓰는 이유는 HS256/ES256 키 체계가
    프로젝트마다 다르고, 만료·폐기된 세션을 Auth가 바로 거절하기 때문이다.
    """

    token = access_token.strip()
    if not token:
        raise AuthTokenError("로그인이 필요합니다.")
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise AuthTokenError("Supabase Auth가 설정되지 않았습니다.")

    async with httpx.AsyncClient(timeout=settings.auth_timeout_seconds) as client:
        response = await client.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_secret_key,
                "Authorization": f"Bearer {token}",
            },
        )
    if response.status_code in {401, 403}:
        raise AuthTokenError("유효하지 않은 로그인 세션입니다.")
    if response.status_code >= 400:
        raise AuthTokenError("로그인 세션을 확인하지 못했습니다.")

    try:
        payload = response.json()
    except ValueError as error:
        raise AuthTokenError("로그인 세션을 확인하지 못했습니다.") from error
    if not isinstance(payload, dict):
        raise AuthTokenError("로그인 세션을 확인하지 못했습니다.")
    return auth_user_from_payload(payload)
