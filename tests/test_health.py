"""서버 상태 확인 endpoint의 기본 계약을 검증한다."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    """health endpoint가 정상 상태를 JSON으로 반환하는지 확인한다."""

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chrome_extension_cors_preflight_is_allowed():
    """Chrome Extension origin의 Tutor JSON preflight를 허용한다."""

    origin = "chrome-extension://abcdefghijklmnop"
    response = client.options(
        "/api/v1/tutor/ask",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "POST" in response.headers["access-control-allow-methods"]


def test_youtube_content_script_cors_preflight_is_allowed():
    """YouTube 페이지에서 실행되는 content script의 preflight를 허용한다."""

    origin = "https://www.youtube.com"
    response = client.options(
        "/api/v1/tutor/ask",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
