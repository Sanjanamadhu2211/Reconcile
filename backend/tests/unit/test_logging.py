import json
import uuid

from fastapi.testclient import TestClient

from app.main import create_app


def test_response_carries_generated_request_id():
    client = TestClient(create_app())

    response = client.get("/missing")

    assert uuid.UUID(response.headers["X-Request-ID"])


def test_incoming_request_id_is_echoed(capsys):
    client = TestClient(create_app())

    response = client.get("/missing", headers={"X-Request-ID": "req-123"})

    assert response.headers["X-Request-ID"] == "req-123"
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    request_log = next(record for record in records if record["message"] == "request")
    assert request_log["request_id"] == "req-123"
    assert request_log["method"] == "GET"
    assert request_log["path"] == "/missing"
    assert request_log["status"] == 404
    assert request_log["duration_ms"] >= 0


def test_request_log_never_contains_credentials(capsys):
    client = TestClient(create_app())

    client.get(
        "/missing",
        headers={"Authorization": "Bearer s3cret-token", "Cookie": "session=abc123"},
    )

    output = capsys.readouterr().err.lower()
    assert "s3cret-token" not in output
    assert "abc123" not in output
    assert "authorization" not in output
    assert "cookie" not in output
