from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """datetime.utcnow() is deprecated in 3.12+ — use an aware UTC timestamp."""
    return datetime.now(timezone.utc)


class User(Base):
    """Registered users. Passwords are stored only as bcrypt hashes."""

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=new_uuid)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    workspaces = relationship(
        "Workspace", back_populates="user", cascade="all, delete-orphan"
    )


class Workspace(Base):
    """
    A workspace = one chat session with its own documents.
    Documents and messages are scoped to it, so it is also the security boundary.
    """

    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, nullable=False, default="New workspace")
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="workspaces")
    messages = relationship(
        "Message", back_populates="workspace", cascade="all, delete-orphan"
    )
    documents = relationship(
        "Document", back_populates="workspace", cascade="all, delete-orphan"
    )


class Message(Base):
    """Every chat message, user and assistant. Powers the history pane."""

    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=new_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    tools_used = Column(String, nullable=True)  # comma-separated, for the UI badges
    created_at = Column(DateTime(timezone=True), default=utcnow)

    workspace = relationship("Workspace", back_populates="messages")


class Document(Base):
    """
    Metadata for every uploaded file. Chunk text + vectors live in Chroma;
    spreadsheets are re-read from `file_path` on demand.
    """

    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=new_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)  # original name, for display only
    file_path = Column(String, nullable=True)  # sanitised on-disk path (UUID name)
    file_type = Column(String, nullable=False)  # pdf | docx | txt | csv | xlsx | url
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    workspace = relationship("Workspace", back_populates="documents")

    @property
    def is_spreadsheet(self) -> bool:
        return self.file_type in ("csv", "xlsx")


class AnswerCache(Base):
    """
    Caches agent answers so a repeated question costs zero Gemini calls.

    Keyed on (workspace, question, doc_version). `doc_version` is the number of
    documents in the workspace — it changes whenever a document is added or
    removed, which invalidates every cached answer for that workspace naturally.
    """

    __tablename__ = "answer_cache"
    __table_args__ = (
        UniqueConstraint("workspace_id", "question_hash", "doc_version", name="uq_answer_cache"),
    )

    id = Column(String, primary_key=True, default=new_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True)
    question_hash = Column(String, nullable=False, index=True)
    doc_version = Column(Integer, nullable=False)
    answer = Column(Text, nullable=False)
    tools_used = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
