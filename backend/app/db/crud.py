import hashlib
import re
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import AnswerCache, Document, Message, User, Workspace

# ── USER ───────────────────────────────────────────────────────────────────────


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def get_user(db: Session, user_id: str) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def create_user(db: Session, username: str, hashed_password: str) -> User:
    user = User(username=username, hashed_password=hashed_password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── WORKSPACE ──────────────────────────────────────────────────────────────────


def get_workspaces(db: Session, user_id: str) -> list[Workspace]:
    return (
        db.query(Workspace)
        .filter(Workspace.user_id == user_id)
        .order_by(Workspace.created_at.desc())
        .all()
    )


def get_workspace(db: Session, workspace_id: str) -> Optional[Workspace]:
    return db.query(Workspace).filter(Workspace.id == workspace_id).first()


def create_workspace(db: Session, user_id: str, name: str) -> Workspace:
    ws = Workspace(user_id=user_id, name=name)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def delete_workspace(db: Session, ws: Workspace) -> None:
    db.delete(ws)  # cascades to messages, documents and cache rows
    db.commit()


# ── MESSAGES ───────────────────────────────────────────────────────────────────


def get_messages(db: Session, workspace_id: str, limit: Optional[int] = None) -> list[Message]:
    """
    Return messages oldest-first. When `limit` is set we take the *newest* N in
    SQL and then reverse — pushing the cap into the query rather than loading the
    whole history and slicing it in Python.
    """
    q = db.query(Message).filter(Message.workspace_id == workspace_id)
    if limit is None:
        return q.order_by(Message.created_at).all()
    rows = q.order_by(Message.created_at.desc()).limit(limit).all()
    return list(reversed(rows))


def add_message(
    db: Session,
    workspace_id: str,
    role: str,
    content: str,
    tools_used: Optional[list[str]] = None,
) -> Message:
    msg = Message(
        workspace_id=workspace_id,
        role=role,
        content=content,
        tools_used=",".join(tools_used) if tools_used else None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


# ── DOCUMENTS ──────────────────────────────────────────────────────────────────


def add_document(
    db: Session,
    workspace_id: str,
    filename: str,
    file_type: str,
    file_path: Optional[str] = None,
    summary: Optional[str] = None,
) -> Document:
    doc = Document(
        workspace_id=workspace_id,
        filename=filename,
        file_type=file_type,
        file_path=file_path,
        summary=summary,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def get_documents(db: Session, workspace_id: str) -> list[Document]:
    return (
        db.query(Document)
        .filter(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc())
        .all()
    )


def get_document(db: Session, doc_id: str) -> Optional[Document]:
    return db.query(Document).filter(Document.id == doc_id).first()


def get_spreadsheet(db: Session, workspace_id: str) -> Optional[Document]:
    """Most recently uploaded spreadsheet in a workspace, if any."""
    return (
        db.query(Document)
        .filter(
            Document.workspace_id == workspace_id,
            Document.file_type.in_(("csv", "xlsx")),
        )
        .order_by(Document.created_at.desc())
        .first()
    )


def delete_document(db: Session, doc: Document) -> None:
    db.delete(doc)
    db.commit()


def get_doc_version(db: Session, workspace_id: str) -> int:
    """
    Cheap change-detector for the answer cache: the document count changes
    whenever the corpus changes, which is exactly when cached answers go stale.
    """
    return (
        db.query(func.count(Document.id))
        .filter(Document.workspace_id == workspace_id)
        .scalar()
        or 0
    )


# ── ANSWER CACHE ───────────────────────────────────────────────────────────────


def hash_question(question: str) -> str:
    """Normalise before hashing so trivial variations still hit the cache."""
    normalised = re.sub(r"\s+", " ", question.strip().lower()).rstrip("?.! ")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def get_cached_answer(
    db: Session, workspace_id: str, question: str, doc_version: int
) -> Optional[AnswerCache]:
    return (
        db.query(AnswerCache)
        .filter(
            AnswerCache.workspace_id == workspace_id,
            AnswerCache.question_hash == hash_question(question),
            AnswerCache.doc_version == doc_version,
        )
        .first()
    )


def set_cached_answer(
    db: Session,
    workspace_id: str,
    question: str,
    doc_version: int,
    answer: str,
    tools_used: Optional[list[str]] = None,
) -> None:
    entry = AnswerCache(
        workspace_id=workspace_id,
        question_hash=hash_question(question),
        doc_version=doc_version,
        answer=answer,
        tools_used=",".join(tools_used) if tools_used else None,
    )
    db.add(entry)
    try:
        db.commit()
    except Exception:
        # A concurrent request may have written the same key first; harmless.
        db.rollback()
