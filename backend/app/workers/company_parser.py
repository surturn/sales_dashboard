import time
from collections.abc import Callable

from backend.app.services.website_parser import WebsiteParserService


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


def parse_company_profiles(companies: list[dict], parser: WebsiteParserService | None = None) -> list[dict]:
    parser = parser or WebsiteParserService()
    parsed: list[dict] = []
    for company in companies:
        website = company.get("website")
        website_data = _with_backoff(lambda website=website: parser.parse_website(website)) if website else {}
        parsed.append({**company, **website_data})
    return parsed
