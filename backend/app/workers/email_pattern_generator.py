from backend.app.services.email_pattern_service import EmailPatternService


def generate_email_candidates(contacts: list[dict], service: EmailPatternService | None = None) -> list[dict]:
    service = service or EmailPatternService()
    generated: list[dict] = []
    for contact in contacts:
        name = (contact.get("name") or "").strip()
        parts = [part for part in name.split() if part]
        first_name = contact.get("first_name") or (parts[0] if parts else "")
        last_name = contact.get("last_name") or (parts[-1] if len(parts) > 1 else "")
        domain = contact.get("company_domain") or ""
        candidates = service.generate_candidates(
            first_name=first_name,
            last_name=last_name,
            domain=domain,
            extra_patterns=contact.get("email_patterns") or [],
        )
        generated.append(
            {
                **contact,
                "first_name": first_name,
                "last_name": last_name,
                "email_candidates": candidates,
            }
        )
    return generated
