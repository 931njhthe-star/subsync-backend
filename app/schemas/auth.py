"""로그인 보호 API의 요청·응답 DTO."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthMeResponse(BaseModel):
    """검증된 세션과 ``public.users``에 맞춘 사용자 요약."""

    id: str = Field(description="Supabase Auth 사용자 ID. JWT sub와 같다.")
    email: str | None = Field(default=None, description="Google 계정 이메일")
    google_account_id: str | None = Field(
        default=None,
        description="Google identity의 고유 ID. users.id와는 다르다.",
    )


class AuthLogoutResponse(BaseModel):
    """로그아웃 이력 갱신 결과."""

    ok: bool = True
