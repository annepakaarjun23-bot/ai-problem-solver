"""Password hashing (Argon2id), JWT access tokens and opaque refresh tokens."""

import asyncio
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import Settings

# argon2-cffi's PasswordHasher uses Argon2id by default.
_hasher = PasswordHasher()

# Used to keep login timing similar whether or not the email exists.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password_sync(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


async def hash_password_async(password: str) -> str:
    # Argon2 is CPU/memory heavy; keep it off the event loop.
    return await asyncio.to_thread(hash_password, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    return await asyncio.to_thread(verify_password_sync, password_hash or _DUMMY_HASH, password) and (
        password_hash is not None
    )


def create_access_token(user_id: uuid.UUID, settings: Settings) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": expires,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, settings.ACCESS_TOKEN_MINUTES * 60


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Validate an access token and return the user id. Raises jwt.PyJWTError / ValueError."""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
    if payload.get("type") != "access":
        raise ValueError("Not an access token")
    return uuid.UUID(payload["sub"])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """Refresh tokens are high-entropy random strings, so a fast SHA-256 is sufficient."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
