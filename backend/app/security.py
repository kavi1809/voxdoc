"""Password hashing and JWT creation/verification."""

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import get_settings

settings = get_settings()

ALGORITHM = "HS256"


def _prehash(password: str) -> bytes:
    """
    bcrypt silently truncates anything past 72 bytes, which would make two long
    passwords sharing a 72-byte prefix interchangeable. SHA-256 first, then
    base64, gives a fixed 44-byte input that is always under the limit.
    """
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(plain), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the DB — treat as a failed login, never a 500.
        return False


def create_token(user_id: str, username: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.access_token_expire_days),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError (incl. ExpiredSignatureError) if the token is bad."""
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
