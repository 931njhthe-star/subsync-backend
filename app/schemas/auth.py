"""인증 API의 요청·응답 DTO."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthMeResponse(BaseModel):
    """현재 Access Token의 사용자 식별 정보를 반환한다."""

    user_id: str = Field(description="Supabase auth.users의 사용자 ID")
    email: str | None = Field(default=None, description="사용자 이메일")
    role: str = Field(description="Supabase JWT role")
    session_id: str | None = Field(
        default=None,
        description="Supabase auth.sessions와 연결되는 session_id claim",
    )
