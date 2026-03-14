from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.workers.lead_pipeline import run_lead_pipeline
from backend.models import Base, import_models
from backend.models.lead import Lead


def build_session():
    import_models()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SessionLocal()


def test_run_lead_pipeline_stores_verified_unique_leads() -> None:
    db = build_session()
    db.add(Lead(email="existing@example.com", company="Known Co", source="google_maps_pipeline", status="verified"))
    db.commit()

    fake_hubspot = Mock()

    with patch(
        "backend.app.workers.lead_pipeline.scrape_companies",
        return_value=[{"company_name": "Acme", "website": "https://acme.example", "phone": "123", "location": "Nairobi"}],
    ), patch(
        "backend.app.workers.lead_pipeline.parse_company_profiles",
        return_value=[
            {
                "company_name": "Acme",
                "company_domain": "acme.example",
                "linkedin_company_url": "https://linkedin.com/company/acme",
                "website": "https://acme.example",
                "phone": "123",
                "location": "Nairobi",
            }
        ],
    ), patch(
        "backend.app.workers.lead_pipeline.discover_company_contacts",
        return_value=[
            {"name": "Ada Lovelace", "title": "Founder", "company": "Acme", "company_domain": "acme.example", "phone": "123"}
        ],
    ), patch(
        "backend.app.workers.lead_pipeline.generate_email_candidates",
        return_value=[
            {
                "name": "Ada Lovelace",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "title": "Founder",
                "company": "Acme",
                "company_domain": "acme.example",
                "phone": "123",
                "email_candidates": ["existing@example.com", "ada@acme.example"],
            }
        ],
    ), patch(
        "backend.app.workers.lead_pipeline.verify_email_candidates",
        return_value=[
            {
                "name": "Ada Lovelace",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "title": "Founder",
                "company": "Acme",
                "company_domain": "acme.example",
                "phone": "123",
                "email": "ada@acme.example",
            }
        ],
    ), patch("backend.app.workers.lead_pipeline.HubSpotClient", return_value=fake_hubspot):
        result = run_lead_pipeline(db, query="coffee shops nairobi", user_id=1, limit=20)

    assert result["records_processed"] == 1
    assert result["records_created"] == 1
    assert db.query(Lead).filter(Lead.email == "ada@acme.example").count() == 1
