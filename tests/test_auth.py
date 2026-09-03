"""Supabase Auth 토큰 검증과 보호 API 계약을 검증한다."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.security import (
    CurrentUser,
    InvalidSupabaseTokenError,
    SupabaseTokenVerifier,
)
from app.main import app


client = TestClient(app)


def test_protected_auth_me_requires_bearer_token():
    """인증 헤더가 없으면 사용자 확인 API가 401을 반환하는지 확인한다."""

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_protected_tutor_api_requires_bearer_token():
    """Tutor API도 공통 인증 dependency를 적용받는지 확인한다."""

    response = client.post(
        "/api/v1/tutor/ask",
        json={
            "video_id": "video-1",
            "timestamp": 0,
            "user_message": "질문",
        },
    )

    assert response.status_code == 401


def test_auth_me_returns_dependency_user():
    """인증 dependency가 반환한 사용자 정보가 안전한 응답 DTO로 변환되는지 확인한다."""

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="user-123",
        email="learner@example.com",
        role="authenticated",
        session_id="session-456",
    )
    try:
        response = client.get("/api/v1/auth/me")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "user-123",
        "email": "learner@example.com",
        "role": "authenticated",
        "session_id": "session-456",
    }


class _SigningKey:
    """PyJWKClient 반환값을 흉내 내는 테스트용 객체."""

    def __init__(self, key):
        self.key = key


def _make_rsa_token(private_key, **claims):
    """테스트용 Supabase 형식의 RS256 JWT를 만든다."""

    now = datetime.now(timezone.utc)
    payload = {
        "iss": "https://example.supabase.co/auth/v1",
        "aud": "authenticated",
        "sub": "user-123",
        "role": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        **claims,
    }
    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def test_jwks_verifier_validates_signature_and_claims(monkeypatch):
    """JWKS 방식이 서명, issuer, audience, expiry를 검증하고 사용자를 반환하는지 확인한다."""

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = SupabaseTokenVerifier(
        supabase_url="https://example.supabase.co",
        verification_mode="jwks",
    )
    monkeypatch.setattr(
        verifier._jwks_client,
        "get_signing_key_from_jwt",
        lambda token: _SigningKey(private_key.public_key()),
    )

    user = verifier.verify(_make_rsa_token(private_key))

    assert isinstance(user, CurrentUser)
    assert user.id == "user-123"
    assert user.role == "authenticated"


def test_jwks_verifier_rejects_expired_token(monkeypatch):
    """만료된 Access Token을 유효한 사용자로 취급하지 않는지 확인한다."""

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = SupabaseTokenVerifier(
        supabase_url="https://example.supabase.co",
        verification_mode="jwks",
    )
    monkeypatch.setattr(
        verifier._jwks_client,
        "get_signing_key_from_jwt",
        lambda token: _SigningKey(private_key.public_key()),
    )
    expired_at = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())

    with pytest.raises(InvalidSupabaseTokenError):
        verifier.verify(_make_rsa_token(private_key, exp=expired_at))


def test_verifier_rejects_unsupported_algorithm():
    """허용하지 않은 JWT 알고리즘을 차단하는지 확인한다."""

    token = jwt.encode({"sub": "user-123"}, key="", algorithm="none")
    verifier = SupabaseTokenVerifier(
        supabase_url="https://example.supabase.co",
        verification_mode="jwks",
    )

    with pytest.raises(InvalidSupabaseTokenError):
        verifier.verify(token)
