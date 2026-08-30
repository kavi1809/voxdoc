"""
Shared FastAPI dependencies for authentication and authorisation.

Previously the app minted JWTs and never verified them — every endpoint was
open, and `user_id` was accepted from the request body, so any caller could act
as any user. These dependencies are what close that hole; every protected route
depends on `get_current_user`, and every route taking a `workspace_id` runs it
through `verify_workspace_access`.
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import User, Workspace
from app.db.session import get_db
from app.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise CREDENTIALS_ERROR

    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise CREDENTIALS_ERROR

    user_id = payload.get("sub")
    if not user_id:
        raise CREDENTIALS_ERROR

    user = crud.get_user(db, user_id)
    if user is None:
        # Valid signature but the user is gone (deleted account, stale token).
        raise CREDENTIALS_ERROR
    return user


def verify_workspace_access(workspace_id: str, user: User, db: Session) -> Workspace:
    """
    Return the workspace only if it belongs to `user`.

    Returns 404 rather than 403 for someone else's workspace: a 403 would confirm
    that the ID exists, letting an attacker enumerate valid workspace IDs.
    """
    ws = crud.get_workspace(db, workspace_id)
    if ws is None or ws.user_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws
