from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_interpret_api():
    payload = {
        "query": "Remind me to submit my assignment tomorrow at 8 AM",
        "timezone": "UTC",
    }
    response = client.post("/api/assistant/interpret", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "CREATE_REMINDER"
    assert data["action_proposal"]["action_type"] == "CREATE_REMINDER"
    assert "assignment" in data["action_proposal"]["parameters"]["title"].lower()


def test_execute_api():
    payload = {
        "action_type": "CREATE_REMINDER",
        "parameters": {
            "title": "Study physics",
            "scheduled_time": "2026-10-13T08:00:00Z",
        },
    }
    response = client.post("/api/assistant/execute", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["record_id"] is not None


def test_history_api():
    response = client.get("/api/assistant/history")
    assert response.status_code == 200
    assert "logs" in response.json()
