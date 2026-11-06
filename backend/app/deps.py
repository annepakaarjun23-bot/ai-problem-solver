"""FastAPI dependencies: database session, current user, shared services."""

from collections.abc import AsyncIterator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import User
from app.security import decode_access_token
from app.services.generation_manager import GenerationManager

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_manager(request: Request) -> GenerationManager:
    return request.app.state.manager


def get_checkpointer(request: Request) -> AsyncPostgresSaver:
    return request.app.state.checkpointer


def settings_dep() -> Settings:
    return get_settings()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except (jwt.PyJWTError, ValueError):
        raise unauthorized from None
    user = await db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user


def validate_origin(request: Request, settings: Settings = Depends(settings_dep)) -> None:
    """CSRF defence for cookie-authenticated endpoints (refresh / logout).

    The browser sends an Origin header on cross-site and same-site POSTs. We require it to be
    one of ALLOWED_ORIGINS. If it is missing we fall back to the Referer; if both are missing
    the request is only accepted outside production (e.g. curl and test clients).
    """
    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if referer:
            parts = referer.split("/", 3)
            origin = "/".join(parts[:3]) if len(parts) >= 3 else None
    if origin:
        if origin.rstrip("/") not in settings.allowed_origins:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")
        return
    if settings.ENVIRONMENT.lower() == "production":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin header required")
