import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.graph import run_agent
from app.agent.tools import load_dataframe
from app.config import get_settings
from app.db import crud
from app.db.models import User
from app.db.session import get_db
from app.deps import get_current_user, verify_workspace_access
from app.rate_limit import CHAT_LIMIT, limiter
from app.services.ingestion import describe_dataframe

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


class ChatRequest(BaseModel):
    workspace_id: str
    message: str = Field(min_length=1, max_length=4000)


class WorkspaceCreate(BaseModel):
    # No user_id here on purpose: it comes from the token. Accepting it from the
    # body previously let any caller create a workspace as any other user.
    name: str = Field(default="New workspace", max_length=100)


@router.post("/workspace")
async def create_workspace(
    body: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = crud.create_workspace(db, user.id, body.name)
    return {"id": ws.id, "name": ws.name, "created_at": ws.created_at}


@router.get("/workspaces")
async def list_workspaces(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return [
        {"id": ws.id, "name": ws.name, "created_at": ws.created_at}
        for ws in crud.get_workspaces(db, user.id)
    ]


@router.delete("/workspace/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.hybrid_search import invalidate
    from app.services.vector_store import delete_workspace_collection

    ws = verify_workspace_access(workspace_id, user, db)
    crud.delete_workspace(db, ws)
    delete_workspace_collection(workspace_id)
    invalidate(workspace_id)
    return {"deleted": workspace_id}


@router.get("/history/{workspace_id}")
async def get_history(
    workspace_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(workspace_id, user, db)
    return [
        {
            "role": m.role,
            "content": m.content,
            "tools_used": m.tools_used.split(",") if m.tools_used else [],
            "created_at": m.created_at,
        }
        for m in crud.get_messages(db, workspace_id)
    ]


@router.post("/message")
async def send_message(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Main chat endpoint: save the question, answer it, save the answer.

    Checks the answer cache first — a repeated question against an unchanged set
    of documents is served from SQLite and costs zero Gemini calls.
    """
    verify_workspace_access(body.workspace_id, user, db)

    crud.add_message(db, body.workspace_id, "user", body.message)
    doc_version = crud.get_doc_version(db, body.workspace_id)

    cached = crud.get_cached_answer(db, body.workspace_id, body.message, doc_version)
    if cached:
        tools_used = cached.tools_used.split(",") if cached.tools_used else []
        crud.add_message(db, body.workspace_id, "assistant", cached.answer, tools_used)
        return {"answer": cached.answer, "tools_used": tools_used, "cached": True}

    # Only the last N turns go to the model — capped in SQL, not sliced in Python.
    history = crud.get_messages(db, body.workspace_id, limit=settings.max_history_messages)
    history_dicts = [{"role": m.role, "content": m.content} for m in history[:-1]]

    # If a spreadsheet is in this workspace, hand the agent its location and
    # schema. The data itself never enters the prompt.
    sheet = crud.get_spreadsheet(db, body.workspace_id)
    sheet_path = sheet_type = schema = None
    if sheet and sheet.file_path:
        sheet_path, sheet_type = sheet.file_path, sheet.file_type
        try:
            schema = describe_dataframe(load_dataframe(sheet_path, sheet_type))
        except Exception as exc:
            logger.warning("Could not describe spreadsheet %s: %s", sheet_path, exc)

    result = await run_agent(
        user_message=body.message,
        chat_history=history_dicts,
        workspace_id=body.workspace_id,
        spreadsheet_path=sheet_path,
        spreadsheet_type=sheet_type,
        spreadsheet_schema=schema,
    )

    crud.add_message(
        db, body.workspace_id, "assistant", result["answer"], result["tools_used"]
    )
    crud.set_cached_answer(
        db, body.workspace_id, body.message, doc_version,
        result["answer"], result["tools_used"],
    )

    return {"answer": result["answer"], "tools_used": result["tools_used"], "cached": False}
