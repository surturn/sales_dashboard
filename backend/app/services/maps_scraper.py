import random
import time
from typing import Any

from backend.app.config import get_settings
from backend.services import ServiceConfigurationError

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional runtime dependency
    sync_playwright = None


class MapsScraperService:
    """Scrapes Google Maps result cards for company discovery."""

    def __init__(self):
        self.settings = get_settings()

    def _sleep(self) -> None:
        delay = max(0.5, self.settings.MAPS_SCRAPE_DELAY_SECONDS + random.uniform(-0.35, 0.45))
        if not self.settings.TASKS_ALWAYS_EAGER:
            time.sleep(delay)

    def search_companies(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if sync_playwright is None:
            raise ServiceConfigurationError("Playwright is required for Google Maps scraping")

        results: list[dict[str, Any]] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.settings.PLAYWRIGHT_HEADLESS)
            page = browser.new_page()
            page.goto("https://www.google.com/maps", wait_until="networkidle")
            search_input = page.locator('input[aria-label="Search Google Maps"]')
            search_input.fill(query)
            search_input.press("Enter")
            page.wait_for_timeout(2500)

            cards = page.locator('a[href*="/place/"]')
            previous_count = 0
            while len(results) < limit:
                card_count = cards.count()
                if card_count == previous_count:
                    break
                previous_count = card_count
                for index in range(min(card_count, limit)):
                    card = cards.nth(index)
                    try:
                        card.scroll_into_view_if_needed(timeout=3000)
                        card.click(timeout=3000)
                        self._sleep()
                        name = (
                            page.locator("h1").first.inner_text(timeout=1500)
                            or card.get_attribute("aria-label")
                            or card.inner_text(timeout=1500)
                        )
                        href = card.get_attribute("href") or ""
                        website = self._extract_text_or_link(page, 'a[data-item-id="authority"]')
                        phone = self._extract_text_or_link(page, 'button[data-item-id*="phone"]')
                        location = self._extract_text_or_link(page, 'button[data-item-id="address"]')
                        results.append(
                            {
                                "company_name": (name or "").strip(),
                                "website": website,
                                "phone": phone,
                                "location": location or href,
                                "maps_url": href,
                            }
                        )
                    except Exception:
                        continue
                page.mouse.wheel(0, 2500)
                self._sleep()

            browser.close()
        return results[:limit]

    @staticmethod
    def _extract_text_or_link(page, selector: str) -> str:
        try:
            element = page.locator(selector).first
            href = element.get_attribute("href")
            if href:
                return href
            text = element.inner_text(timeout=1000)
            return (text or "").strip()
        except Exception:
            return ""
