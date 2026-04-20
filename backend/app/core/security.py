import hmac
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.app.config import get_settings


settings = get_settings()
# Use PBKDF2-SHA256 for new passwords to avoid bcrypt's 72-byte cap while
# keeping a strong, widely supported KDF in the standard passlib set.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
SUPPORTED_HUBSPOT_WEBHOOK_EVENTS = frozenset(
    {
        "contact.creation",
        "contact.deletion",
        "deal.creation",
        "deal.deletion",
    }
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_token(subject: str, token_type: str, expires_delta: timedelta, extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + expires_delta,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str) -> str:
    return create_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRES_MINUTES),
    )


def create_refresh_token(subject: str) -> str:
    return create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRES_DAYS),
    )


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def decode_token_safely(token: str) -> dict[str, Any] | None:
    try:
        return decode_token(token)
    except JWTError:
        return None


def get_hubspot_event_type(event: Mapping[str, Any]) -> str:
    return str(event.get("subscriptionType") or event.get("eventType") or "").strip().lower()


def has_hubspot_object_id(event: Mapping[str, Any]) -> bool:
    return event.get("objectId") not in (None, "") or event.get("object_id") not in (None, "") or event.get("id") not in (None, "")


def is_supported_hubspot_webhook_event(event: Mapping[str, Any]) -> bool:
    return get_hubspot_event_type(event) in SUPPORTED_HUBSPOT_WEBHOOK_EVENTS


def has_valid_shared_secret(expected_secret: str, provided_secret: str | None) -> bool:
    if not expected_secret or not provided_secret:
        return False
    return hmac.compare_digest(expected_secret.strip(), provided_secret.strip())
