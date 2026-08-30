"""
Rate limiting on the auth endpoints.

Without a limit, /login is an unmetered password-guessing oracle. The shared
fixture disables the limiter so it cannot bleed across tests, so this file
re-enables it explicitly.
"""

import pytest

from app.rate_limit import limiter


@pytest.fixture
def limited(app_client, monkeypatch):
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    yield app_client
    limiter.reset()


def test_login_attempts_are_rate_limited(limited):
    statuses = [
        limited.post(
            "/api/auth/login", json={"username": "alice", "password": "wrongpassword"}
        ).status_code
        for _ in range(15)
    ]
    assert 429 in statuses, "brute-force attempts were never throttled"
    # The limit must kick in before an attacker gets many guesses.
    assert statuses.index(429) <= 11


def test_registration_is_rate_limited(limited):
    statuses = [
        limited.post(
            "/api/auth/register", json={"username": f"user{i}", "password": "password123"}
        ).status_code
        for i in range(10)
    ]
    assert 429 in statuses
