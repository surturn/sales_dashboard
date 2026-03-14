from typing import Iterable


class EmailPatternService:
    PATTERNS = (
        "{first}@{domain}",
        "{first}.{last}@{domain}",
        "{first}{last}@{domain}",
        "{first_initial}.{last}@{domain}",
    )

    def generate_candidates(self, first_name: str, last_name: str, domain: str, extra_patterns: Iterable[str] | None = None) -> list[str]:
        first = (first_name or "").strip().lower()
        last = (last_name or "").strip().lower()
        domain = (domain or "").strip().lower()
        if not first or not last or not domain:
            return []

        values = {
            "first": first,
            "last": last,
            "first_initial": first[0],
            "domain": domain,
        }
        patterns = list(self.PATTERNS)
        for pattern in extra_patterns or []:
            if pattern == "first.last":
                patterns.append("{first}.{last}@{domain}")
            elif pattern == "first":
                patterns.append("{first}@{domain}")

        seen: set[str] = set()
        candidates: list[str] = []
        for pattern in patterns:
            candidate = pattern.format(**values)
            if candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
        return candidates
