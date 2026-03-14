import re
import time
from typing import Any

import httpx

from backend.app.config import get_settings


TARGET_TITLES = (
    "founder",
    "ceo",
    "marketing director",
    "head of growth",
    "sales director",
)


class LinkedInService:
    def __init__(self, http_client: httpx.Client | None = None):
        self.settings = get_settings()
        self.client = http_client or httpx.Client(timeout=20, follow_redirects=True)

    def discover_decision_makers(
        self,
        *,
        company_name: str,
        linkedin_company_url: str | None = None,
        fallback_pages: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        sources = [url for url in [linkedin_company_url, *(fallback_pages or [])] if url]
        if not sources:
            return []

        if not self.settings.TASKS_ALWAYS_EAGER:
            time.sleep(self.settings.LINKEDIN_SCRAPE_DELAY_SECONDS)

        employees: list[dict[str, Any]] = []
        for source in sources:
            try:
                response = self.client.get(source)
                response.raise_for_status()
            except Exception:
                continue

            text = response.text
            for title in TARGET_TITLES:
                matches = re.findall(rf"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*[,\-\|]\s*([^<\n]{{1,80}}{re.escape(title)}[^<\n]{{0,80}})", text, flags=re.IGNORECASE)
                for name, extracted_title in matches:
                    employees.append(
                        {
                            "name": name.strip(),
                            "title": extracted_title.strip(),
                            "company": company_name,
                            "source_url": source,
                        }
                    )

        deduped: dict[tuple[str, str], dict[str, Any]] = {}
        for employee in employees:
            key = (employee["name"].lower(), employee["title"].lower())
            deduped[key] = employee
        return list(deduped.values())
