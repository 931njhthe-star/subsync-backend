"""Supabase Auth 기반 인증 확인 API.

Google 로그인과 Access/Refresh Token 발급은 Supabase Auth 및 프론트 클라이언트가
담당한다. 백엔드는 발급된 Access Token을 검증하고 현재 사용자 정보를 제공한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.security import CurrentUser
from app.schemas.auth import AuthMeResponse


router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get("/me", response_model=AuthMeResponse)
def read_current_user(
    current_user: CurrentUser = Depends(get_current_user),
) -> AuthMeResponse:
    """현재 Bearer Token에 해당하는 사용자 정보를 반환한다."""

    return AuthMeResponse(
        user_id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        session_id=current_user.session_id,
    )
