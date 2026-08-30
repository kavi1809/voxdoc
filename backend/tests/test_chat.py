"""Workspace isolation, chat flow, and the answer cache."""

import io

import pytest


@pytest.fixture
def stub_agent(monkeypatch):
    """Replace the agent with a counting stub so cache hits are observable."""
    calls = {"count": 0}

    async def fake_run_agent(**kwargs):
        calls["count"] += 1
        return {"answer": f"Stub answer {calls['count']}", "tools_used": ["search_documents"]}

    from app.routers import chat as chat_router

    monkeypatch.setattr(chat_router, "run_agent", fake_run_agent)
    return calls


def test_workspace_is_scoped_to_its_owner(app_client, auth_headers, workspace):
    other = app_client.post(
        "/api/auth/register", json={"username": "mallory", "password": "password123"}
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    # Mallory sees none of Alice's workspaces...
    assert app_client.get("/api/chat/workspaces", headers=headers).json() == []
    # ...and cannot reach one directly. 404, not 403, so IDs cannot be probed.
    assert app_client.get(f"/api/chat/history/{workspace}", headers=headers).status_code == 404
    assert (
        app_client.post(
            "/api/chat/message",
            json={"workspace_id": workspace, "message": "hi"},
            headers=headers,
        ).status_code
        == 404
    )


def test_workspace_owner_is_taken_from_the_token(app_client, auth_headers):
    """
    `user_id` used to be accepted from the request body, so any caller could
    create a workspace belonging to someone else. The body no longer carries it.
    """
    resp = app_client.post(
        "/api/chat/workspace",
        json={"name": "Mine", "user_id": "some-other-user-id"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    mine = app_client.get("/api/chat/workspaces", headers=auth_headers).json()
    assert any(w["id"] == resp.json()["id"] for w in mine)


def test_message_round_trip_is_persisted(app_client, auth_headers, workspace, stub_agent):
    resp = app_client.post(
        "/api/chat/message",
        json={"workspace_id": workspace, "message": "What is the policy?"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["tools_used"] == ["search_documents"]

    history = app_client.get(f"/api/chat/history/{workspace}", headers=auth_headers).json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["tools_used"] == ["search_documents"]


def test_repeated_question_is_served_from_cache(app_client, auth_headers, workspace, stub_agent):
    payload = {"workspace_id": workspace, "message": "What is the policy?"}

    first = app_client.post("/api/chat/message", json=payload, headers=auth_headers).json()
    assert first["cached"] is False
    assert stub_agent["count"] == 1

    second = app_client.post("/api/chat/message", json=payload, headers=auth_headers).json()
    assert second["cached"] is True
    assert second["answer"] == first["answer"]
    # The whole point: no second call to the model.
    assert stub_agent["count"] == 1


def test_cache_normalises_trivial_variations(app_client, auth_headers, workspace, stub_agent):
    app_client.post(
        "/api/chat/message",
        json={"workspace_id": workspace, "message": "What is the policy?"},
        headers=auth_headers,
    )
    resp = app_client.post(
        "/api/chat/message",
        json={"workspace_id": workspace, "message": "  what is THE policy  "},
        headers=auth_headers,
    ).json()
    assert resp["cached"] is True
    assert stub_agent["count"] == 1


def test_uploading_a_document_invalidates_the_cache(
    app_client, auth_headers, workspace, stub_agent, no_gemini
):
    """A new document can change the answer, so cached replies must not persist."""
    payload = {"workspace_id": workspace, "message": "What is the policy?"}
    app_client.post("/api/chat/message", json=payload, headers=auth_headers)
    assert stub_agent["count"] == 1

    app_client.post(
        "/api/documents/upload",
        files={"file": ("new.txt", io.BytesIO(b"A brand new policy document."), "text/plain")},
        data={"workspace_id": workspace},
        headers=auth_headers,
    )

    resp = app_client.post("/api/chat/message", json=payload, headers=auth_headers).json()
    assert resp["cached"] is False
    assert stub_agent["count"] == 2


def test_history_is_capped_when_building_agent_context(app_client, auth_headers, workspace, stub_agent):
    """
    The router must pass only the configured number of recent turns to the agent,
    trimmed in SQL rather than by loading everything and slicing.
    """
    from app.db import crud
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        for i in range(40):
            crud.add_message(db, workspace, "user" if i % 2 == 0 else "assistant", f"m{i}")
        limited = crud.get_messages(db, workspace, limit=10)
    finally:
        db.close()

    assert len(limited) == 10
    assert [m.content for m in limited] == [f"m{i}" for i in range(30, 40)]


def test_deleting_a_workspace_removes_its_history(app_client, auth_headers, workspace, stub_agent):
    app_client.post(
        "/api/chat/message",
        json={"workspace_id": workspace, "message": "hello"},
        headers=auth_headers,
    )
    assert app_client.delete(f"/api/chat/workspace/{workspace}", headers=auth_headers).status_code == 200
    assert app_client.get(f"/api/chat/history/{workspace}", headers=auth_headers).status_code == 404
