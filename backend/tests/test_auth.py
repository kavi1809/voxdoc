"""
Authentication and authorisation.

The unauthenticated-access test is the important one here: the app previously
minted JWTs and never verified them, so every endpoint was wide open.
"""

import pytest

PROTECTED_GET = [
    "/api/chat/workspaces",
    "/api/chat/history/some-id",
    "/api/documents/some-id",
]


def test_register_returns_token(app_client):
    resp = app_client.post(
        "/api/auth/register", json={"username": "bob", "password": "password123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["username"] == "bob"


def test_register_rejects_duplicate_username(app_client, auth_headers):
    resp = app_client.post(
        "/api/auth/register", json={"username": "alice", "password": "password123"}
    )
    assert resp.status_code == 400


def test_register_rejects_short_password(app_client):
    resp = app_client.post(
        "/api/auth/register", json={"username": "carol", "password": "short"}
    )
    assert resp.status_code == 422


def test_login_succeeds_and_rejects_bad_password(app_client, auth_headers):
    ok = app_client.post(
        "/api/auth/login", json={"username": "alice", "password": "password123"}
    )
    assert ok.status_code == 200

    bad = app_client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrongpassword"}
    )
    assert bad.status_code == 401


def test_login_does_not_leak_whether_a_username_exists(app_client, auth_headers):
    """Both failures must be indistinguishable, or usernames can be enumerated."""
    no_user = app_client.post(
        "/api/auth/login", json={"username": "nobody", "password": "password123"}
    )
    bad_password = app_client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrongpassword"}
    )
    assert no_user.status_code == bad_password.status_code == 401
    assert no_user.json()["detail"] == bad_password.json()["detail"]


@pytest.mark.parametrize("path", PROTECTED_GET)
def test_protected_routes_reject_anonymous_requests(app_client, path):
    assert app_client.get(path).status_code == 401


@pytest.mark.parametrize("path", PROTECTED_GET)
def test_protected_routes_reject_garbage_tokens(app_client, path):
    resp = app_client.get(path, headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_expired_token_is_rejected(app_client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import jwt

    from app.config import get_settings

    settings = get_settings()
    expired = jwt.encode(
        {
            "sub": "someone",
            "username": "alice",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.secret_key,
        algorithm="HS256",
    )
    resp = app_client.get(
        "/api/chat/workspaces", headers={"Authorization": f"Bearer {expired}"}
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


def test_token_signed_with_another_key_is_rejected(app_client):
    """Guards against the app ever being started with signature checks disabled."""
    from datetime import datetime, timedelta, timezone

    import jwt

    forged = jwt.encode(
        {
            "sub": "someone",
            "username": "mallory",
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
        },
        "the-wrong-secret",
        algorithm="HS256",
    )
    resp = app_client.get(
        "/api/chat/workspaces", headers={"Authorization": f"Bearer {forged}"}
    )
    assert resp.status_code == 401


def test_long_passwords_are_not_interchangeable():
    """
    bcrypt truncates at 72 bytes. Without the SHA-256 pre-hash, two passwords
    sharing a 72-byte prefix would authenticate each other.
    """
    from app.security import hash_password, verify_password

    base = "x" * 72
    stored = hash_password(base + "AAAA")
    assert verify_password(base + "AAAA", stored)
    assert not verify_password(base + "BBBB", stored)
