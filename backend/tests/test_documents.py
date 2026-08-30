"""Upload handling: path traversal, size limits, ownership, and deletion."""

import io
import os


def _txt(content: str = "The remote work policy allows three days from home.") -> bytes:
    return content.encode("utf-8")


def test_upload_indexes_a_text_document(app_client, auth_headers, workspace, no_gemini):
    resp = app_client.post(
        "/api/documents/upload",
        files={"file": ("policy.txt", io.BytesIO(_txt()), "text/plain")},
        data={"workspace_id": workspace},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "policy.txt"
    assert body["chunks"] >= 1
    assert body["is_spreadsheet"] is False


def test_traversal_filename_cannot_escape_the_upload_directory(
    app_client, auth_headers, workspace, no_gemini
):
    """
    The old code interpolated the client-supplied filename straight into a path.
    The saved file must land inside upload_dir under a generated name.
    """
    evil = "../../../../evil.txt"
    resp = app_client.post(
        "/api/documents/upload",
        files={"file": (evil, io.BytesIO(_txt()), "text/plain")},
        data={"workspace_id": workspace},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    upload_dir = os.path.abspath(app_client.settings.upload_dir)
    written = os.listdir(upload_dir)
    assert len(written) == 1
    assert ".." not in written[0]
    # And the file really is inside the directory, not just named innocuously.
    assert os.path.abspath(os.path.join(upload_dir, written[0])).startswith(upload_dir)


def test_oversized_upload_is_rejected(app_client, auth_headers, workspace, no_gemini, monkeypatch):
    limit_bytes = app_client.settings.max_upload_mb * 1024 * 1024
    resp = app_client.post(
        "/api/documents/upload",
        files={"file": ("big.txt", io.BytesIO(b"x" * (limit_bytes + 1024)), "text/plain")},
        data={"workspace_id": workspace},
        headers=auth_headers,
    )
    assert resp.status_code == 413
    # The partial file must not be left behind.
    assert os.listdir(app_client.settings.upload_dir) == []


def test_unsupported_extension_is_rejected(app_client, auth_headers, workspace):
    resp = app_client.post(
        "/api/documents/upload",
        files={"file": ("payload.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        data={"workspace_id": workspace},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_cannot_upload_into_someone_elses_workspace(app_client, auth_headers, workspace, no_gemini):
    other = app_client.post(
        "/api/auth/register", json={"username": "mallory", "password": "password123"}
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    resp = app_client.post(
        "/api/documents/upload",
        files={"file": ("x.txt", io.BytesIO(_txt()), "text/plain")},
        data={"workspace_id": workspace},
        headers=headers,
    )
    assert resp.status_code == 404


def test_spreadsheet_upload_stores_the_file_for_later_analysis(
    app_client, auth_headers, workspace, no_gemini
):
    """
    Spreadsheets used to be handed back to the browser as JSON and never
    persisted, so they vanished on refresh and could not be analysed server-side.
    """
    csv = b"region,sales\nNorth,100\nSouth,250\n"
    resp = app_client.post(
        "/api/documents/upload",
        files={"file": ("data.csv", io.BytesIO(csv), "text/csv")},
        data={"workspace_id": workspace},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_spreadsheet"] is True
    assert "region" in body["schema"]

    listed = app_client.get(f"/api/documents/{workspace}", headers=auth_headers).json()
    assert listed[0]["is_spreadsheet"] is True
    assert os.listdir(app_client.settings.upload_dir)  # the file is still on disk


def test_delete_removes_the_document_and_its_file(
    app_client, auth_headers, workspace, no_gemini
):
    upload = app_client.post(
        "/api/documents/upload",
        files={"file": ("policy.txt", io.BytesIO(_txt()), "text/plain")},
        data={"workspace_id": workspace},
        headers=auth_headers,
    ).json()

    assert os.listdir(app_client.settings.upload_dir)

    resp = app_client.delete(f"/api/documents/{upload['doc_id']}", headers=auth_headers)
    assert resp.status_code == 200

    assert app_client.get(f"/api/documents/{workspace}", headers=auth_headers).json() == []
    assert os.listdir(app_client.settings.upload_dir) == []
