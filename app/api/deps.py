"""FastAPI 공통 의존성.

인증이 필요한 라우트는 이 모듈의 ``get_current_user``를 dependency로 선언한다.
라우터마다 토큰 파싱을 반복하지 않고, 모든 보호 API가 동일한 401/503 정책을
사용하도록 하는 경계 계층이다.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import (
    CurrentUser,
    InvalidSupabaseTokenError,
    SupabaseAuthNotConfiguredError,
    SupabaseAuthUnavailableError,
    get_supabase_token_verifier,
)


bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Supabase Auth에서 발급한 Access Token",
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """Bearer Access Token을 검증하고 인증된 사용자를 반환한다.

    Returns:
        검증된 Supabase 사용자의 ID와 최소 메타데이터.

    Raises:
        HTTPException: 토큰이 없거나 유효하지 않으면 401, 서버 인증 설정이 없거나
            Supabase 검증 서버가 일시적으로 unavailable이면 503을 반환한다.
    """

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer Access Token이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return get_supabase_token_verifier().verify(credentials.credentials)
    except InvalidSupabaseTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 Access Token입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except SupabaseAuthNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth가 서버에 설정되지 않았습니다.",
        ) from exc
    except SupabaseAuthUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth 검증 서버를 일시적으로 사용할 수 없습니다.",
        ) from exc
