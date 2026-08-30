import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import crud
from app.db.models import User
from app.db.session import get_db
from app.deps import get_current_user, verify_workspace_access
from app.rate_limit import UPLOAD_LIMIT, limiter
from app.services.gemini import generate_summary
from app.services.hybrid_search import invalidate
from app.services.ingestion import (
    chunk_text,
    describe_dataframe,
    extract_and_chunk,
    extract_text_from_url,
    get_dataframe,
)
from app.services.vector_store import delete_document_chunks, store_chunks

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

SUPPORTED_TYPES = {"pdf", "docx", "txt", "csv", "xlsx"}
SPREADSHEET_TYPES = {"csv", "xlsx"}


async def _save_upload(file: UploadFile, ext: str) -> str:
    """
    Stream an upload to disk under a generated name, enforcing the size cap.

    The filename is NOT derived from `file.filename`. That value is fully
    attacker-controlled, and the previous code interpolated it straight into a
    path — `..\\..\\evil.py` escaped the upload directory entirely.
    """
    os.makedirs(settings.upload_dir, exist_ok=True)
    save_path = os.path.join(settings.upload_dir, f"{uuid.uuid4().hex}.{ext}")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with open(save_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        413, f"File is larger than the {settings.max_upload_mb} MB limit"
                    )
                out.write(chunk)
    except Exception:
        if os.path.exists(save_path):
            os.unlink(save_path)
        raise
    return save_path


@router.post("/upload")
@limiter.limit(UPLOAD_LIMIT)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    workspace_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save a document, index it, and generate a one-off summary."""
    verify_workspace_access(workspace_id, user, db)

    if not file.filename or "." not in file.filename:
        raise HTTPException(400, "File must have an extension")
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in SUPPORTED_TYPES:
        raise HTTPException(400, f"Unsupported file type: .{ext}")

    save_path = await _save_upload(file, ext)

    try:
        if ext in SPREADSHEET_TYPES:
            # Spreadsheets are not chunked or embedded — they are analysed with
            # pandas on demand. We keep the file and describe its schema.
            df = get_dataframe(save_path, ext)
            summary = (
                f"Spreadsheet with {len(df)} rows and {len(df.columns)} columns: "
                f"{', '.join(str(c) for c in df.columns)}"
            )
            doc = crud.add_document(
                db, workspace_id, file.filename, ext, file_path=save_path, summary=summary
            )
            return {
                "doc_id": doc.id,
                "filename": doc.filename,
                "summary": summary,
                "schema": describe_dataframe(df),
                "is_spreadsheet": True,
            }

        chunks = extract_and_chunk(save_path, ext)
        if not chunks:
            raise HTTPException(400, "No readable text could be extracted from that file")

        doc = crud.add_document(db, workspace_id, file.filename, ext, file_path=save_path)
        store_chunks(workspace_id, chunks, doc.id)
        invalidate(workspace_id)  # the BM25 index is now stale

        doc.summary = await generate_summary(" ".join(chunks[:5]))
        db.commit()

        return {
            "doc_id": doc.id,
            "filename": doc.filename,
            "summary": doc.summary,
            "chunks": len(chunks),
            "is_spreadsheet": False,
        }
    except HTTPException:
        if os.path.exists(save_path):
            os.unlink(save_path)
        raise
    except Exception as exc:
        if os.path.exists(save_path):
            os.unlink(save_path)
        logger.exception("Upload failed for %s", file.filename)
        raise HTTPException(500, f"Could not process the file: {exc}") from exc


@router.post("/url")
@limiter.limit(UPLOAD_LIMIT)
async def ingest_url(
    request: Request,
    url: str = Form(...),
    workspace_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scrape a public web page and index it like a document."""
    verify_workspace_access(workspace_id, user, db)

    title, text = await extract_text_from_url(url)  # validates against SSRF
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(400, "No readable text found at that URL")

    doc = crud.add_document(db, workspace_id, title or url, "url", file_path=None)
    store_chunks(workspace_id, chunks, doc.id)
    invalidate(workspace_id)

    doc.summary = await generate_summary(text[:8000])
    db.commit()

    return {
        "doc_id": doc.id,
        "filename": doc.filename,
        "summary": doc.summary,
        "chunks": len(chunks),
        "is_spreadsheet": False,
    }


@router.get("/{workspace_id}")
async def list_documents(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(workspace_id, user, db)
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "type": d.file_type,
            "summary": d.summary,
            "is_spreadsheet": d.is_spreadsheet,
            "created_at": d.created_at,
        }
        for d in crud.get_documents(db, workspace_id)
    ]


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a document everywhere: DB row, vectors, BM25 cache, and disk."""
    doc = crud.get_document(db, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    verify_workspace_access(doc.workspace_id, user, db)

    workspace_id, file_path = doc.workspace_id, doc.file_path
    crud.delete_document(db, doc)
    delete_document_chunks(workspace_id, doc_id)
    invalidate(workspace_id)
    if file_path and os.path.exists(file_path):
        try:
            os.unlink(file_path)
        except OSError as exc:
            logger.warning("Could not delete %s: %s", file_path, exc)

    return {"deleted": doc_id}
