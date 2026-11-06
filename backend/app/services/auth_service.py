"""Signup, login and refresh-token session handling."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ServiceError
from app.models import AuthSession, User
from app.security import (
    generate_refresh_token,
    hash_password_async,
    hash_refresh_token,
    verify_password,
)

log = logging.getLogger(__name__)

# A rotated token presented again within this window is treated as a benign race
# (e.g. two tabs refreshing at once). Later reuse suggests theft and revokes all sessions.
REUSE_GRACE = timedelta(seconds=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _create_session(db: AsyncSession, user_id: uuid.UUID, settings: Settings) -> str:
    """Create a refresh-token session row and return the raw (unhashed) token."""
    token = generate_refresh_token()
    db.add(
        AuthSession(
            user_id=user_id,
            refresh_token_hash=hash_refresh_token(token),
            expires_at=_now() + timedelta(days=settings.REFRESH_TOKEN_DAYS),
        )
    )
    return token


async def signup(db: AsyncSession, email: str, password: str, settings: Settings) -> tuple[User, str]:
    email = email.strip().lower()
    existing = await db.scalar(select(User.id).where(User.email == email))
    if existing is not None:
        raise ServiceError(409, "An account with this email already exists")
    user = User(email=email, password_hash=await hash_password_async(password))
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ServiceError(409, "An account with this email already exists") from None
    refresh = await _create_session(db, user.id, settings)
    await db.commit()
    return user, refresh


async def login(db: AsyncSession, email: str, password: str, settings: Settings) -> tuple[User, str]:
    email = email.strip().lower()
    user = await db.scalar(select(User).where(User.email == email))
    ok = await verify_password(user.password_hash if user else None, password)
    if user is None or not ok:
        raise ServiceError(401, "Invalid email or password")
    refresh = await _create_session(db, user.id, settings)
    await db.commit()
    return user, refresh


async def refresh(db: AsyncSession, raw_token: str | None, settings: Settings) -> tuple[User, str]:
    """Rotate a refresh token: revoke the presented one and issue a new one."""
    invalid = ServiceError(401, "Invalid or expired session")
    if not raw_token:
        raise invalid
    session = await db.scalar(
        select(AuthSession)
        .where(AuthSession.refresh_token_hash == hash_refresh_token(raw_token))
        .with_for_update()
    )
    if session is None:
        raise invalid
    now = _now()
    if session.revoked_at is not None:
        if now - session.revoked_at > REUSE_GRACE:
            # Token reuse after rotation/logout: revoke every active session of this user.
            await db.execute(
                update(AuthSession)
                .where(AuthSession.user_id == session.user_id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            await db.commit()
            log.warning("Refresh token reuse detected for user %s; sessions revoked", session.user_id)
        raise invalid
    if session.expires_at <= now:
        raise invalid
    user = await db.get(User, session.user_id)
    if user is None:
        raise invalid
    session.revoked_at = now
    new_token = await _create_session(db, user.id, settings)
    await db.commit()
    return user, new_token


async def logout(db: AsyncSession, raw_token: str | None) -> None:
    if not raw_token:
        return
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.refresh_token_hash == hash_refresh_token(raw_token),
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    await db.commit()
