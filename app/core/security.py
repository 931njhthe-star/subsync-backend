"""Supabase Auth Access Token 검증을 담당하는 보안 모듈.

Supabase가 발급한 토큰을 애플리케이션 자체의 JWT로 다시 발급하지 않는다. 백엔드는
요청의 ``Authorization: Bearer`` 토큰을 검증한 뒤 토큰의 ``sub``를 신뢰할 수 있는
사용자 ID로 사용한다.

Supabase 프로젝트가 비대칭 서명 키를 사용하면 JWKS로 로컬 검증하고, 레거시
HS256 프로젝트이면 Supabase Auth의 ``/auth/v1/user`` 검증 API를 사용한다. 이렇게
두 방식을 지원하면 프로젝트의 JWT 서명 설정을 바꾸더라도 API 계층을 변경하지 않아도
된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError

from app.core.config import settings


class SupabaseAuthError(Exception):
    """Supabase Access Token을 인증할 수 없을 때 사용하는 기본 예외."""


class InvalidSupabaseTokenError(SupabaseAuthError):
    """토큰이 없거나 만료·변조되었거나 필수 claim이 없을 때 발생한다."""


class SupabaseAuthNotConfiguredError(SupabaseAuthError):
    """백엔드에 Supabase 인증 설정이 주입되지 않았을 때 발생한다."""


class SupabaseAuthUnavailableError(SupabaseAuthError):
    """JWKS 또는 Supabase Auth 검증 API에 일시적으로 접근할 수 없을 때 발생한다."""


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """검증된 Supabase 토큰에서 추출한 최소 사용자 정보.

    ``claims``에는 디버깅이나 이후 권한 확장에 필요한 원본 claim을 보관하지만,
    API 응답으로 그대로 노출하지 않는다. 특히 권한 판단은 클라이언트가 보낸
    사용자 정보가 아니라 검증된 토큰과 DB 정책을 기준으로 해야 한다.
    """

    id: str
    email: str | None = None
    role: str = "authenticated"
    session_id: str | None = None
    claims: dict[str, Any] | None = None


class SupabaseTokenVerifier:
    """Supabase 프로젝트 설정에 맞춰 Access Token을 검증한다.

    Args:
        supabase_url: Supabase 프로젝트 URL.
        supabase_key: HS256 검증 API 호출에 사용할 publishable/anon key.
        audience: JWT의 ``aud`` claim. Supabase 사용자 토큰 기본값은
            ``authenticated``다.
        issuer: JWT의 ``iss`` claim. 비워 두면 ``{supabase_url}/auth/v1``를 사용한다.
        verification_mode: ``auto``, ``jwks`` 또는 ``auth_api``.
        jwks_cache_seconds: JWKS 키셋 캐시 시간(초).
        request_timeout_seconds: Supabase Auth 검증 API timeout(초).
    """

    _JWKS_ALGORITHMS = ("RS256", "ES256", "EdDSA")
    _SUPPORTED_MODES = {"auto", "jwks", "auth_api"}

    def __init__(
        self,
        *,
        supabase_url: str,
        supabase_key: str = "",
        audience: str = "authenticated",
        issuer: str | None = None,
        verification_mode: str = "auto",
        jwks_cache_seconds: int = 600,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        normalized_url = supabase_url.strip().rstrip("/")
        normalized_mode = verification_mode.strip().lower()

        if not normalized_url:
            raise SupabaseAuthNotConfiguredError("SUPABASE_URL is not configured")
        if normalized_mode not in self._SUPPORTED_MODES:
            raise SupabaseAuthNotConfiguredError(
                "SUPABASE_AUTH_VERIFICATION_MODE must be auto, jwks, or auth_api"
            )

        self.supabase_url = normalized_url
        self.supabase_key = supabase_key.strip()
        self.audience = audience.strip() or "authenticated"
        self.issuer = issuer.strip() if issuer and issuer.strip() else f"{normalized_url}/auth/v1"
        self.verification_mode = normalized_mode
        self.request_timeout_seconds = request_timeout_seconds
        self._jwks_client = PyJWKClient(
            f"{normalized_url}/auth/v1/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=max(jwks_cache_seconds, 1),
        )

    def verify(self, token: str) -> CurrentUser:
        """Access Token을 검증하고 현재 사용자를 반환한다.

        ``HS256``은 서버가 공유 JWT secret을 직접 보관·배포하지 않도록 Supabase
        Auth의 user endpoint에서 검증한다. 비대칭 알고리즘은 Supabase JWKS를 통해
        서명을 로컬에서 검증한다.
        """

        if not token or not token.strip():
            raise InvalidSupabaseTokenError("Access Token is empty")

        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise InvalidSupabaseTokenError("Access Token header is invalid") from exc

        algorithm = header.get("alg")
        if algorithm == "HS256":
            return self._verify_with_auth_api(token)

        if algorithm not in self._JWKS_ALGORITHMS:
            raise InvalidSupabaseTokenError("Unsupported Access Token algorithm")

        if self.verification_mode == "auth_api":
            return self._verify_with_auth_api(token)

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self._JWKS_ALGORITHMS),
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except PyJWKClientError as exc:
            # JWKS가 일시적으로 접근 불가한 경우에만 Auth API fallback을 허용한다.
            # 서명 검증 실패(InvalidTokenError)는 절대로 fallback으로 우회하지 않는다.
            if self.verification_mode == "auto" and self.supabase_key:
                return self._verify_with_auth_api(token)
            raise SupabaseAuthUnavailableError("Supabase JWKS is unavailable") from exc
        except InvalidTokenError as exc:
            raise InvalidSupabaseTokenError("Access Token claims are invalid") from exc

        return self._claims_to_user(claims)

    def _verify_with_auth_api(self, token: str) -> CurrentUser:
        """Supabase Auth의 ``/user`` endpoint에 토큰 검증을 위임한다."""

        if not self.supabase_key:
            raise SupabaseAuthNotConfiguredError(
                "SUPABASE_KEY is required for Auth API token verification"
            )

        try:
            with httpx.Client(timeout=self.request_timeout_seconds) as client:
                response = client.get(
                    f"{self.supabase_url}/auth/v1/user",
                    headers={
                        "apikey": self.supabase_key,
                        "Authorization": f"Bearer {token}",
                    },
                )
        except httpx.HTTPError as exc:
            raise SupabaseAuthUnavailableError(
                "Supabase Auth verification endpoint is unavailable"
            ) from exc

        if response.status_code in {401, 403}:
            raise InvalidSupabaseTokenError("Supabase rejected the Access Token")
        if response.status_code >= 400:
            raise SupabaseAuthUnavailableError(
                "Supabase Auth verification endpoint returned an error"
            )

        try:
            user = response.json()
        except ValueError as exc:
            raise SupabaseAuthUnavailableError(
                "Supabase Auth returned an invalid user response"
            ) from exc

        if not isinstance(user, dict):
            raise SupabaseAuthUnavailableError("Supabase user response is not an object")

        user_id = user.get("id")
        if not isinstance(user_id, str) or not user_id:
            raise SupabaseAuthUnavailableError("Supabase user response has no id")

        return CurrentUser(
            id=user_id,
            email=user.get("email") if isinstance(user.get("email"), str) else None,
            role=user.get("role") if isinstance(user.get("role"), str) else "authenticated",
            claims=user,
        )

    @staticmethod
    def _claims_to_user(claims: dict[str, Any]) -> CurrentUser:
        """검증이 끝난 JWT claim을 API 계층에서 사용할 사용자 객체로 변환한다."""

        user_id = claims.get("sub")
        if not isinstance(user_id, str) or not user_id:
            raise InvalidSupabaseTokenError("Access Token has no user id")

        return CurrentUser(
            id=user_id,
            email=claims.get("email") if isinstance(claims.get("email"), str) else None,
            role=claims.get("role") if isinstance(claims.get("role"), str) else "authenticated",
            session_id=claims.get("session_id")
            if isinstance(claims.get("session_id"), str)
            else None,
            claims=claims,
        )


@lru_cache(maxsize=1)
def get_supabase_token_verifier() -> SupabaseTokenVerifier:
    """프로세스에서 재사용할 Supabase 토큰 검증기를 생성한다.

    JWKS client는 키셋을 캐시하므로 요청마다 객체를 새로 만들면 안 된다. 설정 변경은
    서버 재시작 후 반영된다.
    """

    return SupabaseTokenVerifier(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_key,
        audience=settings.supabase_jwt_audience,
        issuer=settings.supabase_jwt_issuer,
        verification_mode=settings.supabase_auth_verification_mode,
        jwks_cache_seconds=settings.supabase_jwks_cache_seconds,
        request_timeout_seconds=settings.supabase_auth_timeout_seconds,
    )
