from backend.app.services.email_pattern_service import EmailPatternService


def test_generate_candidates_returns_expected_patterns() -> None:
    service = EmailPatternService()

    candidates = service.generate_candidates("Ada", "Lovelace", "example.com")

    assert candidates == [
        "ada@example.com",
        "ada.lovelace@example.com",
        "adalovelace@example.com",
        "a.lovelace@example.com",
    ]
