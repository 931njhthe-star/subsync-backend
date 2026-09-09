"""로그인 보호 API와 users/login_history 동기화를 검증한다."""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.v1.auth import get_login_history_repository, get_user_repository
from app.core.security import AuthTokenError, AuthUser, auth_user_from_payload, extract_google_account_id
from app.db.login_history import LoginHistoryRepository
from app.db.users import UserRepository, UserRow
from app.main import app


client = TestClient(app)

SAMPLE_USER = AuthUser(
    id="11111111-1111-1111-1111-111111111111",
    email="learner@example.com",
    google_account_id="google-account-1",
)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_me_requires_bearer_token():
    """토큰 없는 /me 요청은 401이다."""

    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "로그인이 필요합니다."


def test_me_rejects_invalid_access_token(monkeypatch):
    """Supabase가 거절한 토큰은 401이다."""

    async def fake_fetch(_token: str) -> AuthUser:
        raise AuthTokenError("유효하지 않은 로그인 세션입니다.")

    monkeypatch.setattr("app.api.deps.fetch_supabase_auth_user", fake_fetch)
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "유효하지 않은 로그인 세션입니다."


def test_google_account_id_comes_from_google_identity():
    """users.google_account_id는 Google identity id를 사용한다."""

    payload = {
        "id": SAMPLE_USER.id,
        "email": SAMPLE_USER.email,
        "identities": [{"provider": "google", "id": "google-account-1"}],
    }
    assert extract_google_account_id(payload) == "google-account-1"
    user = auth_user_from_payload(payload)
    assert user.id == SAMPLE_USER.id
    assert user.google_account_id == "google-account-1"


def test_me_upserts_users_and_inserts_login_history():
    """/me 성공 시 users upsert와 login_history insert가 한 번씩 호출된다."""

    calls: dict[str, object] = {}

    class FakeUsers:
        is_configured = True

        async def upsert_from_auth(self, auth_user: AuthUser) -> UserRow:
            calls["auth_user"] = auth_user
            return UserRow(
                id=auth_user.id,
                google_account_id=auth_user.google_account_id,
                email=auth_user.email,
                created_at="2026-09-08T00:00:00+00:00",
                last_login_at="2026-09-08T00:00:00+00:00",
            )

    class FakeHistory:
        is_configured = True

        async def record_login(self, user_id: str) -> dict[str, object]:
            calls["login_user_id"] = user_id
            return {"user_id": user_id}

    async def override_user() -> AuthUser:
        return SAMPLE_USER

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_user_repository] = lambda: FakeUsers()
    app.dependency_overrides[get_login_history_repository] = lambda: FakeHistory()
    try:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer test-token"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == SAMPLE_USER.id
    assert body["email"] == SAMPLE_USER.email
    assert body["google_account_id"] == SAMPLE_USER.google_account_id
    assert calls["auth_user"] == SAMPLE_USER
    assert calls["login_user_id"] == SAMPLE_USER.id


def test_me_without_supabase_config_returns_503():
    """DB 키가 없으면 로그인 동기화를 성공으로 바꾸지 않는다."""

    class Unconfigured:
        is_configured = False

    async def override_user() -> AuthUser:
        return SAMPLE_USER

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_user_repository] = lambda: Unconfigured()
    app.dependency_overrides[get_login_history_repository] = lambda: Unconfigured()
    try:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer test-token"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 503


def test_logout_closes_open_login_history():
    """/logout은 열린 이력의 logout_at만 갱신한다."""

    closed: list[str] = []

    class FakeHistory:
        is_configured = True

        async def record_logout(self, user_id: str) -> None:
            closed.append(user_id)

    async def override_user() -> AuthUser:
        return SAMPLE_USER

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_login_history_repository] = lambda: FakeHistory()
    try:
        response = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer test-token"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert closed == [SAMPLE_USER.id]


def test_user_repository_inserts_erd_columns(monkeypatch):
    """신규 사용자는 ERD의 users 컬럼만 INSERT한다."""

    captured: dict[str, object] = {}
    pending = {"empty_get": True}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            if pending["empty_get"]:
                pending["empty_get"] = False
                return []
            return [captured["json"]]

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url, *, headers, params):
            captured["get_url"] = url
            return FakeResponse()

        async def post(self, url, *, headers, json):
            captured["post_url"] = url
            captured["json"] = json
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    repository = UserRepository(url="https://example.supabase.co", secret_key="server-key")
    row = asyncio.run(repository.upsert_from_auth(SAMPLE_USER))

    assert captured["post_url"] == "https://example.supabase.co/rest/v1/users"
    assert set(captured["json"]) == {
        "id",
        "google_account_id",
        "email",
        "created_at",
        "last_login_at",
    }
    assert captured["json"]["id"] == SAMPLE_USER.id
    assert captured["json"]["google_account_id"] == SAMPLE_USER.google_account_id
    UUID(str(row.id))


def test_login_history_row_matches_erd_columns():
    """login_history INSERT 행이 화면 ERD 컬럼과 같다."""

    repository = LoginHistoryRepository(url="https://example.supabase.co", secret_key="server-key")
    row = repository.login_row(SAMPLE_USER.id)
    UUID(str(row["id"]))
    assert set(row) == {"id", "user_id", "login_at", "logout_at", "last_access_at"}
    assert row["user_id"] == SAMPLE_USER.id
    assert row["logout_at"] is None
    assert row["last_access_at"] == row["login_at"]
