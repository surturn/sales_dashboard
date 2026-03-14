import time
from collections.abc import Callable

from backend.app.config import get_settings
from backend.app.services.smtp_verifier import SMTPVerifierService


def _with_backoff(func: Callable[[], dict], max_retries: int = 3) -> dict:
    delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception:
            if attempt >= max_retries:
                raise
            time.sleep(delay)
            delay *= 2
    return {}


def verify_email_candidates(leads: list[dict], verifier: SMTPVerifierService | None = None) -> list[dict]:
    verifier = verifier or SMTPVerifierService()
    settings = get_settings()
    verified: list[dict] = []
    for lead in leads:
        verified_email = None
        last_result: dict | None = None
        for candidate in lead.get("email_candidates", []):
            result = _with_backoff(lambda candidate=candidate: verifier.verify(candidate, settings.EMAIL_FROM))
            last_result = result
            if result.get("is_valid"):
                verified_email = candidate
                break
        verified.append({**lead, "email": verified_email, "verification": last_result or {}})
    return verified
