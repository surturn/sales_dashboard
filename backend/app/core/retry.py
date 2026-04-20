"""Retry utilities for agent nodes.

Provides an async-friendly `with_retry` decorator using Tenacity and a
simple in-memory `CircuitBreaker` used to fail-fast when downstream
services are unhealthy.
"""

from __future__ import annotations

import asyncio
import random
import time
import logging
from collections import defaultdict
from functools import wraps
from typing import Callable, Optional

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    wait_random,
    retry_if_exception_type,
    before_sleep_log,
    RetryError,
)

from backend.app.config import get_settings
from backend.app.core.observability import get_logger

settings = get_settings()
std_log = logging.getLogger(__name__)
log = get_logger(__name__)


def with_retry(func: Optional[Callable] = None, *, max_attempts: Optional[int] = None, base_delay: Optional[float] = None, service: Optional[str] = None):
    """Decorator factory that applies tenacity retries to async functions.

    Usage:
        @with_retry(service="groq")
        async def call_groq(...):
            ...

    The decorator checks the module-level `circuit_breaker` before
    attempting calls and records successes / failures.
    """

    max_a = max_attempts or getattr(settings, "AGENT_MAX_RETRIES", 3)
    base_d = base_delay or getattr(settings, "AGENT_RETRY_BASE_DELAY", 1.0)

    def decorator(f: Callable):
        tenacity_decorator = retry(
            stop=stop_after_attempt(max_a),
            wait=wait_exponential(multiplier=base_d, min=base_d, max=base_d * 16) + wait_random(0, 0.5),
            retry=retry_if_exception_type((Exception,)),
            before_sleep=before_sleep_log(std_log, logging.WARNING),
            reraise=True,
        )

        # Apply tenacity to the inner call
        @tenacity_decorator
        @wraps(f)
        async def _retrying(*args, **kwargs):
            return await f(*args, **kwargs)

        @wraps(f)
        async def wrapper(*args, **kwargs):
            svc = service
            if svc and circuit_breaker.is_open(svc):
                log.warning("circuit_open", service=svc)
                raise RuntimeError(f"Circuit open for service {svc}")

            try:
                result = await _retrying(*args, **kwargs)
            except Exception as exc:
                if svc:
                    circuit_breaker.record_failure(svc)
                log.error("retry_failed", service=svc, error=str(exc))
                raise
            else:
                if svc:
                    circuit_breaker.record_success(svc)
                return result

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


class CircuitBreaker:
    """In-memory circuit breaker keyed by service name.

    Not distributed — acceptable for single-process agent runners.
    """

    def __init__(self, threshold: Optional[int] = None, reset_timeout: float = 60.0):
        self.threshold = threshold or getattr(settings, "AGENT_CIRCUIT_BREAKER_THRESHOLD", 5)
        self.reset_timeout = reset_timeout
        self._failures: dict[str, int] = defaultdict(int)
        self._opened_at: dict[str, float] = {}

    def is_open(self, service: str) -> bool:
        if service not in self._opened_at:
            return False
        if time.time() - self._opened_at[service] > self.reset_timeout:
            # reset
            self._failures[service] = 0
            del self._opened_at[service]
            return False
        return self._failures[service] >= self.threshold

    def record_success(self, service: str):
        self._failures[service] = 0
        self._opened_at.pop(service, None)

    def record_failure(self, service: str):
        self._failures[service] += 1
        if self._failures[service] >= self.threshold:
            self._opened_at[service] = time.time()


# Module-level singleton used by all agents
circuit_breaker = CircuitBreaker()

