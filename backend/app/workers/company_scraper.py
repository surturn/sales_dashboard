import time
from collections.abc import Callable

from backend.app.services.maps_scraper import MapsScraperService


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


def scrape_companies(query: str, limit: int = 20, scraper: MapsScraperService | None = None) -> list[dict]:
    scraper = scraper or MapsScraperService()
    return _with_backoff(lambda: scraper.search_companies(query=query, limit=limit))
