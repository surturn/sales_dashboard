import re
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from backend.app.config import get_settings


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href = ""
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag == "a":
            self._current_href = dict(attrs).get("href", "")
            self._text_parts = []

    def handle_data(self, data: str):
        if self._current_href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag == "a" and self._current_href:
            self.links.append((self._current_href, "".join(self._text_parts).strip().lower()))
            self._current_href = ""
            self._text_parts = []


class WebsiteParserService:
    def __init__(self, http_client: httpx.Client | None = None):
        self.settings = get_settings()
        self.client = http_client or httpx.Client(timeout=20, follow_redirects=True)

    def parse_website(self, website_url: str) -> dict[str, Any]:
        if not website_url:
            return {
                "linkedin_company_url": None,
                "team_page": None,
                "about_page": None,
                "contact_page": None,
                "email_patterns": [],
            }

        if not self.settings.TASKS_ALWAYS_EAGER:
            time.sleep(self.settings.WEBSITE_PARSE_DELAY_SECONDS)

        response = self.client.get(website_url)
        response.raise_for_status()
        html = response.text
        parser = _AnchorParser()
        parser.feed(html)
        base_url = str(response.url)
        links = [(urljoin(base_url, href), text) for href, text in parser.links]
        email_patterns = self._extract_email_patterns(html)

        return {
            "linkedin_company_url": self._find_matching_link(links, ("linkedin.com/company", "linkedin.com/in")),
            "team_page": self._find_matching_text_link(links, ("team", "leadership", "staff")),
            "about_page": self._find_matching_text_link(links, ("about", "story", "mission")),
            "contact_page": self._find_matching_text_link(links, ("contact", "reach", "talk")),
            "email_patterns": email_patterns,
            "company_domain": urlparse(base_url).netloc.replace("www.", ""),
        }

    @staticmethod
    def _find_matching_link(links: list[tuple[str, str]], needles: tuple[str, ...]) -> str | None:
        for href, _ in links:
            lowered = href.lower()
            if any(needle in lowered for needle in needles):
                return href
        return None

    @staticmethod
    def _find_matching_text_link(links: list[tuple[str, str]], labels: tuple[str, ...]) -> str | None:
        for href, text in links:
            if any(label in text for label in labels):
                return href
        return None

    @staticmethod
    def _extract_email_patterns(html: str) -> list[str]:
        email_matches = re.findall(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", html)
        patterns = []
        if email_matches:
            patterns.append("first.last")
        if "contact@" in html.lower():
            patterns.append("first")
        return list(dict.fromkeys(patterns))
