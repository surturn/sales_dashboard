from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from backend.app.config import get_settings


settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    headers_enabled=False,
)

rate_limit_exceeded_handler = _rate_limit_exceeded_handler

__all__ = ["SlowAPIMiddleware", "RateLimitExceeded", "limiter", "rate_limit_exceeded_handler"]
