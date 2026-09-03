"""서버 상태 확인 endpoint의 기본 계약을 검증한다."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    """health endpoint가 정상 상태를 JSON으로 반환하는지 확인한다."""

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
