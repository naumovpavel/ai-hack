from fastapi.testclient import TestClient

from interview_api.config import Settings
from interview_api.main import create_app


def test_health_returns_ok() -> None:
    app = create_app(settings=Settings(app_env="test", _env_file=None))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
