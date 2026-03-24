"""API smoke tests — no DB required for root and OpenAPI."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_app_info():
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data.get("app") == "Rhino ReID"
    assert "docs" in data


def test_openapi_json_available():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec.get("openapi") is not None
    assert "/predict/history" in spec.get("paths", {})


def test_predict_history_requires_auth():
    """Backend path is /predict/history (browser uses /api via Vite proxy)."""
    r = client.get("/predict/history")
    assert r.status_code == 401
