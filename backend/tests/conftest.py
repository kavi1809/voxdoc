"""
Shared test fixtures.

Every Gemini call is stubbed, so the suite runs offline and costs nothing. Local
embeddings run for real — they are fast, free, and exercising them is the point.
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import the app package from the backend root regardless of where pytest runs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("DEBUG", "true")


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """A TestClient with an isolated DB, upload dir and Chroma directory."""
    from app.config import get_settings

    # get_settings is lru_cached, so every module that did `settings =
    # get_settings()` at import time holds a reference to this one object.
    # Mutating it therefore redirects all of them; clearing the cache and
    # setting env vars would not, because already-imported modules keep the
    # old instance and tests would silently share one upload/Chroma directory.
    settings = get_settings()
    uploads = tmp_path / "uploads"
    chroma = tmp_path / "chroma"
    uploads.mkdir(parents=True, exist_ok=True)
    chroma.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "upload_dir", str(uploads))
    monkeypatch.setattr(settings, "chroma_persist_dir", str(chroma))

    from app.db import session as session_module
    from app.db.models import Base

    # In-memory SQLite with a shared connection, so every session in the test
    # sees the same database.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "SessionLocal", TestingSession)

    # Reset vector-store and BM25 state between tests.
    from app.services import hybrid_search, vector_store

    monkeypatch.setattr(vector_store, "_client", None)
    hybrid_search._cache.clear()

    # Every test request comes from the same client address, so the shared
    # in-memory rate limiter would start returning 429 partway through the run.
    # Limits are exercised separately in test_rate_limit.py.
    from app.rate_limit import limiter

    monkeypatch.setattr(limiter, "enabled", False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        client.settings = settings
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(app_client):
    """Register a user and return ready-to-use Authorization headers."""
    resp = app_client.post(
        "/api/auth/register", json={"username": "alice", "password": "password123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def workspace(app_client, auth_headers):
    resp = app_client.post(
        "/api/chat/workspace", json={"name": "Test workspace"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.fixture
def no_gemini(monkeypatch):
    """Replace every outbound Gemini call with a deterministic stub."""

    async def fake_summary(text: str) -> str:
        return "A stub summary."

    async def fake_transcribe(data: bytes, mime: str) -> str:
        return "stub transcription"

    from app.routers import documents as documents_router
    from app.services import gemini

    monkeypatch.setattr(gemini, "generate_summary", fake_summary)
    monkeypatch.setattr(gemini, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(documents_router, "generate_summary", fake_summary)
    return fake_summary
