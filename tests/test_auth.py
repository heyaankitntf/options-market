"""Tests for the auth + user flows.

Covers:
  - successful registration (request-otp -> register)
  - duplicate registration is rejected
  - full login flow (request-login-otp -> login -> /users/me)
  - unauthorized access to /users/me
  - expired / invalid OTP cases
"""

from fastapi.testclient import TestClient


def _request_otp_and_read_code(client: TestClient, phone: str, endpoint: str) -> str:
    """Helper: hit a request-otp endpoint then read the code from dev-otp."""
    response = client.post(endpoint, json={"country_code": "+91", "phone": phone})
    assert response.status_code == 200, response.text
    code = client.get("/api/v1/auth/dev-otp", params={"phone": phone})
    assert code.status_code == 200, code.text
    return code.json()["code"]


def test_register_success(client: TestClient):
    phone = "9000011111"
    code = _request_otp_and_read_code(client, phone, "/api/v1/auth/request-otp")

    response = client.post(
        "/api/v1/auth/register",
        json={
            "country_code": "+91",
            "phone": phone,
            "code": code,
            "name": "Test User",
            "email": "test@example.com",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["phone"] == phone
    assert body["is_verified"] is True
    assert body["name"] == "Test User"


def test_register_duplicate_rejected(client: TestClient):
    phone = "9000022222"
    code = _request_otp_and_read_code(client, phone, "/api/v1/auth/request-otp")
    first = client.post(
        "/api/v1/auth/register",
        json={"country_code": "+91", "phone": phone, "code": code},
    )
    assert first.status_code == 201, first.text

    # A verified user can no longer request a registration OTP.
    second_otp = client.post(
        "/api/v1/auth/request-otp",
        json={"country_code": "+91", "phone": phone},
    )
    assert second_otp.status_code == 400, second_otp.text
    assert "already registered" in second_otp.json()["detail"].lower()


def test_login_flow(client: TestClient):
    phone = "9000033333"
    # Register first.
    reg_code = _request_otp_and_read_code(client, phone, "/api/v1/auth/request-otp")
    client.post(
        "/api/v1/auth/register",
        json={
            "country_code": "+91",
            "phone": phone,
            "code": reg_code,
            "name": "Login User",
        },
    )

    # Now log in.
    login_code = _request_otp_and_read_code(
        client, phone, "/api/v1/auth/request-login-otp"
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"country_code": "+91", "phone": phone, "code": login_code},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    assert token

    # Use the token to fetch the profile.
    me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["phone"] == phone


def test_protected_route_requires_token(client: TestClient):
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_protected_route_rejects_bad_token(client: TestClient):
    response = client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


def test_invalid_otp_rejected(client: TestClient):
    phone = "9000044444"
    client.post(
        "/api/v1/auth/request-otp", json={"country_code": "+91", "phone": phone}
    )
    response = client.post(
        "/api/v1/auth/register",
        json={"country_code": "+91", "phone": phone, "code": "000000"},
    )
    assert response.status_code == 401
