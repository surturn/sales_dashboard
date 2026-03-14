import time
from collections.abc import Callable

from backend.app.services.linkedin_service import LinkedInService


def _with_backoff(func: Callable[[], list[dict]], max_retries: int = 3) -> list[dict]:
    delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception:
            if attempt >= max_retries:
                raise
            time.sleep(delay)
            delay *= 2
    return []


def discover_company_contacts(companies: list[dict], service: LinkedInService | None = None) -> list[dict]:
    service = service or LinkedInService()
    contacts: list[dict] = []
    for company in companies:
        people = _with_backoff(
            lambda company=company: service.discover_decision_makers(
                company_name=company.get("company_name") or company.get("company") or "",
                linkedin_company_url=company.get("linkedin_company_url"),
                fallback_pages=[company.get("team_page"), company.get("about_page")],
            )
        )
        for person in people:
            contacts.append({**company, **person})
    return contacts
