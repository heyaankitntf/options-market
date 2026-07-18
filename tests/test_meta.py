"""Tests for the meta endpoints."""

from fastapi.testclient import TestClient


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "otp-auth-system"


def test_root(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()
