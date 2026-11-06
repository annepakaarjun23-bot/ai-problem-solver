"""Authentication endpoints."""

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import get_current_user, get_db, settings_dep, validate_origin
from app.errors import ServiceError
from app.models import User
from app.schemas import AuthResponse, LoginRequest, SignupRequest, UserOut
from app.security import create_access_token
from app.services import auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

REFRESH_COOKIE_PATH = "/api/v1/auth"


def _cookie_secure(settings: Settings) -> bool:
    # Keep the default secure, while allowing an explicit false for initial HTTP deployments.
    return settings.COOKIE_SECURE


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_TOKEN_DAYS * 86400,
        httponly=True,
        secure=_cookie_secure(settings),
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=_cookie_secure(settings),
        samesite="lax",
    )


def _auth_response(user: User, settings: Settings) -> AuthResponse:
    token, expires_in = create_access_token(user.id, settings)
    return AuthResponse(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(settings_dep),
):
    user, refresh_token = await auth_service.signup(db, body.email, body.password, settings)
    _set_refresh_cookie(response, refresh_token, settings)
    return _auth_response(user, settings)


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(settings_dep),
):
    user, refresh_token = await auth_service.login(db, body.email, body.password, settings)
    _set_refresh_cookie(response, refresh_token, settings)
    return _auth_response(user, settings)


@router.post("/refresh", response_model=AuthResponse, dependencies=[Depends(validate_origin)])
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(settings_dep),
):
    raw = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    try:
        user, new_token = await auth_service.refresh(db, raw, settings)
    except ServiceError as exc:
        # Drop the useless cookie so the browser stops sending it.
        failure = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        _clear_refresh_cookie(failure, settings)
        return failure
    _set_refresh_cookie(response, new_token, settings)
    return _auth_response(user, settings)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(validate_origin)],
)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(settings_dep),
):
    await auth_service.logout(db, request.cookies.get(settings.REFRESH_COOKIE_NAME))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, settings)
    return response


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
