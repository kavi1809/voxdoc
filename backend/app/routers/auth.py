from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import crud
from app.db.session import get_db
from app.deps import get_current_user
from app.db.models import User
from app.rate_limit import LOGIN_LIMIT, REGISTER_LIMIT, limiter
from app.security import create_token, hash_password, verify_password

router = APIRouter()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    user_id: str


@router.post("/register", response_model=TokenResponse)
@limiter.limit(REGISTER_LIMIT)
async def register(request: Request, body: Credentials, db: Session = Depends(get_db)):
    if crud.get_user_by_username(db, body.username):
        raise HTTPException(status_code=400, detail="Username already taken")
    user = crud.create_user(db, body.username, hash_password(body.password))
    return TokenResponse(
        access_token=create_token(user.id, user.username),
        username=user.username,
        user_id=user.id,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(LOGIN_LIMIT)
async def login(request: Request, body: Credentials, db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, body.username)
    # Same message and same work either way — a distinct "no such user" reply
    # would let an attacker enumerate valid usernames.
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return TokenResponse(
        access_token=create_token(user.id, user.username),
        username=user.username,
        user_id=user.id,
    )


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    """Lets the frontend validate a stored token on page load."""
    return {"id": user.id, "username": user.username}
