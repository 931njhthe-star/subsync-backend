"""라우터 공통 의존성."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import AuthTokenError, AuthUser, fetch_supabase_auth_user


# 헤더가 없을 때 FastAPI 기본 403 대신 401을 내려 로그인 필요를 분명히 한다.
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthUser:
    """Authorization Bearer 토큰을 검증하고 JWT sub에 해당하는 사용자를 반환한다.

    요청 body의 ``user_id``는 사용하지 않는다. Refresh Token은 받지 않는다.
    """

    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )
    try:
        return await fetch_supabase_auth_user(credentials.credentials)
    except AuthTokenError as error:
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "설정되지 않았습니다" in str(error)
            else status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(status_code=status_code, detail=str(error)) from error
"""API dependency 모음."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException

from app.core.config import settings


async def get_saved_words_user_id(
    dev_user_id: Annotated[
        str | None,
        Header(
            alias="X-Dev-User-ID",
            description=(
                "OAuth 연결 전 로컬 테스트용 사용자 UUID. "
                "운영 환경에서는 사용하지 않음"
            ),
        ),
    ] = None,
) -> UUID:
    """OAuth 연결 전 개발 환경에서 저장 단어의 테스트 사용자 ID를 반환한다.

    실제 Google OAuth가 연결되면 이 dependency를 Supabase Access Token의 JWT
    ``sub``를 검증하는 dependency로 교체한다. 운영 환경에서 임의의 header로
    사용자를 지정하지 못하도록 production에서는 항상 요청을 거부한다.
    """

    if settings.ENV.strip().lower() == "production":
        raise HTTPException(
            status_code=401,
            detail="저장 단어 API는 로그인 후 사용할 수 있습니다.",
        )
    if not dev_user_id:
        raise HTTPException(
            status_code=401,
            detail="OAuth 연결 전에는 X-Dev-User-ID 헤더가 필요합니다.",
        )
    try:
        return UUID(dev_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="X-Dev-User-ID는 올바른 UUID여야 합니다.",
        ) from exc
