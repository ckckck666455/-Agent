from fastapi.testclient import TestClient

from shopagent.api import create_app


def test_health_and_root(agent, settings):
    app = create_app(settings=settings, agent=agent)
    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "offline"
    root = client.get("/")
    assert root.status_code == 200
    assert "小美" in root.text
    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert "p95_ms" in metrics.json()["metrics"]


def test_chat_and_history(agent, settings):
    client = TestClient(create_app(settings=settings, agent=agent))
    response = client.post(
        "/api/chat",
        json={
            "message": "我是油皮，想买300以内的面霜",
            "session_id": "api-session",
            "user_id": "user_001",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["reply"]
    assert data["intent"]["intent"] == "pre_sales"
    assert data["tool_calls"]

    history = client.get("/api/sessions/api-session?user_id=user_001")
    assert history.status_code == 200
    assert len(history.json()["messages"]) >= 2

    forbidden = client.get("/api/sessions/api-session?user_id=user_002")
    assert forbidden.status_code == 403


def test_reset_session(agent, settings):
    client = TestClient(create_app(settings=settings, agent=agent))
    client.post(
        "/api/chat",
        json={"message": "你好", "session_id": "reset-session", "user_id": "user_001"},
    )
    reset = client.delete("/api/sessions/reset-session?user_id=user_001")
    assert reset.status_code == 200
    assert client.get("/api/sessions/reset-session?user_id=user_001").status_code == 404


def test_profile_endpoint(agent, settings):
    client = TestClient(create_app(settings=settings, agent=agent))
    response = client.patch("/api/profile/api_user", json={"skin_type": "敏感肌", "budget": 260})
    assert response.status_code == 200
    assert response.json()["profile"]["skin_type"] == "敏感肌"
    assert client.get("/api/profile/api_user").json()["profile"]["budget"] == 260
