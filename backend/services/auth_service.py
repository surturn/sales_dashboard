from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token_safely,
    get_password_hash,
    verify_password,
)
from backend.models.session import Session as SessionModel
from backend.models.user import User
from backend.services.user_service import create_user, get_user_by_email


def register_user(
    db: Session,
    email: str,
    password: str,
    full_name: str | None = None,
    company_name: str | None = None,
) -> User:
    if get_user_by_email(db, email=email):
        raise ValueError("User already exists")
    return create_user(
        db,
        email=email,
        hashed_password=get_password_hash(password),
        full_name=full_name,
        company_name=company_name,
    )


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email=email)
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return user


def _persist_refresh_token(
    db: Session,
    user: User,
    refresh_token: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> None:
    session = SessionModel(
        user_id=user.id,
        refresh_token=refresh_token,
        user_agent=user_agent,
        ip_address=ip_address,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(session)
    db.commit()


def create_tokens_for_user(
    db: Session,
    user: User,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> dict[str, str]:
    access_token = create_access_token(subject=user.email)
    refresh_token = create_refresh_token(subject=user.email)
    _persist_refresh_token(db, user=user, refresh_token=refresh_token, user_agent=user_agent, ip_address=ip_address)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


def revoke_refresh_token(db: Session, refresh_token: str) -> None:
    session = db.scalar(select(SessionModel).where(SessionModel.refresh_token == refresh_token))
    if session is not None:
        session.revoked_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()


def validate_refresh_token(db: Session, refresh_token: str) -> User | None:
    session = db.scalar(select(SessionModel).where(SessionModel.refresh_token == refresh_token))
    payload = decode_token_safely(refresh_token)
    if session is None or session.revoked_at is not None or payload is None or payload.get("type") != "refresh":
        return None
    if session.expires_at < datetime.now(timezone.utc):
        revoke_refresh_token(db, refresh_token)
        return None
    email = payload.get("sub")
    return get_user_by_email(db, email=email) if email else None
