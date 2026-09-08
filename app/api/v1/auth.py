"""로그인 세션 확인과 앱 사용자·로그인 이력 동기화 API."""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import AuthUser
from app.db.login_history import LoginHistoryRepository
from app.db.users import UserRepository, UserRow
from app.schemas.auth import AuthLogoutResponse, AuthMeResponse


router = APIRouter(prefix="/auth", tags=["Auth"])


@lru_cache(maxsize=1)
def get_user_repository() -> UserRepository:
    """프로세스에서 공유할 ``users`` 저장소를 생성한다."""

    return UserRepository(
        url=settings.supabase_url,
        secret_key=settings.supabase_secret_key,
        timeout_seconds=settings.auth_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_login_history_repository() -> LoginHistoryRepository:
    """프로세스에서 공유할 ``login_history`` 저장소를 생성한다."""

    return LoginHistoryRepository(
        url=settings.supabase_url,
        secret_key=settings.supabase_secret_key,
        timeout_seconds=settings.auth_timeout_seconds,
    )


def _require_configured(repository: UserRepository | LoginHistoryRepository) -> None:
    """테이블 기록이 가능해야 로그인 동기화가 끝난 것으로 본다."""

    if not repository.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase 사용자 저장소가 설정되지 않았습니다.",
        )


@router.get("/me", response_model=AuthMeResponse)
async def read_current_user(
    current_user: AuthUser = Depends(get_current_user),
    users: UserRepository = Depends(get_user_repository),
    history: LoginHistoryRepository = Depends(get_login_history_repository),
) -> AuthMeResponse:
    """토큰을 검증한 뒤 ``public.users``를 upsert하고 로그인 이력을 한 줄 추가한다."""

    _require_configured(users)
    _require_configured(history)
    try:
        row: UserRow = await users.upsert_from_auth(current_user)
        await history.record_login(current_user.id)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="사용자 정보를 저장하지 못했습니다.",
        ) from error
    return AuthMeResponse(
        id=row.id,
        email=row.email,
        google_account_id=row.google_account_id,
    )


@router.post("/logout", response_model=AuthLogoutResponse)
async def logout_current_user(
    current_user: AuthUser = Depends(get_current_user),
    history: LoginHistoryRepository = Depends(get_login_history_repository),
) -> AuthLogoutResponse:
    """열린 ``login_history`` 행에 ``logout_at``을 기록한다.

    Access Token 폐기는 확장 프로그램이 Supabase Auth에 요청한다. 이 endpoint는
    앱 이력만 갱신한다.
    """

    _require_configured(history)
    try:
        await history.record_logout(current_user.id)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="로그아웃 이력을 저장하지 못했습니다.",
        ) from error
    return AuthLogoutResponse(ok=True)
