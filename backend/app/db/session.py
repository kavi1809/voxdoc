"""
Database engine + session factory.

This module exists to break a circular import: previously `main.py` imported the
routers, and every router did `from app.main import get_db` — but `get_db` was
defined *after* the router import ran, so startup died with:

    ImportError: cannot import name 'get_db' from partially initialized module
    'app.main' (most likely due to a circular import)

Keeping the DB wiring in a leaf module that imports nothing from the app means
both `main.py` and the routers can depend on it without a cycle.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

settings = get_settings()

# check_same_thread=False is required because FastAPI serves requests from a
# thread pool and SQLite otherwise refuses connections opened on another thread.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create tables. Called from the app lifespan, not at import time."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
