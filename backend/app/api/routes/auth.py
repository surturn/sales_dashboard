from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.core.dependencies import get_current_user
from backend.app.core.rate_limit import limiter
from backend.app.database import get_db
from backend.models.user import User
from backend.schemas.auth import LoginRequest, Token, TokenRefreshRequest, UserCreate, UserRead
from backend.services.auth_service import (
    authenticate_user,
    create_tokens_for_user,
    register_user,
    revoke_refresh_token,
    validate_refresh_token,
)


router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        key=settings.ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRES_MINUTES * 60,
    )
    response.set_cookie(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRES_DAYS * 24 * 60 * 60,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.ACCESS_TOKEN_COOKIE_NAME)
    response.delete_cookie(settings.REFRESH_TOKEN_COOKIE_NAME)


@router.post("/signup", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def signup(request: Request, user_in: UserCreate, db: Session = Depends(get_db)) -> User:
    try:
        return register_user(
            db,
            email=user_in.email,
            password=user_in.password,
            full_name=user_in.full_name,
            company_name=user_in.company_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/login", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def login(
    request: Request,
    credentials: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    user_agent: str | None = Header(default=None),
) -> Token:
    user = authenticate_user(db, email=credentials.email, password=credentials.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tokens = create_tokens_for_user(db, user=user, user_agent=user_agent)
    _set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    return Token(**tokens)


@router.post("/refresh", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def refresh_token(
    request: Request,
    response: Response,
    payload: TokenRefreshRequest | None = None,
    refresh_cookie: str | None = Cookie(default=None, alias=settings.REFRESH_TOKEN_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> Token:
    refresh_token_value = payload.refresh_token if payload else refresh_cookie
    if not refresh_token_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    user = validate_refresh_token(db, refresh_token=refresh_token_value)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    tokens = create_tokens_for_user(db, user=user)
    _set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    return Token(**tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def logout(
    request: Request,
    response: Response,
    payload: TokenRefreshRequest | None = None,
    refresh_cookie: str | None = Cookie(default=None, alias=settings.REFRESH_TOKEN_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> None:
    refresh_token_value = payload.refresh_token if payload else refresh_cookie
    if refresh_token_value:
        revoke_refresh_token(db, refresh_token_value)
    _clear_auth_cookies(response)


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
