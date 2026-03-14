from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, import_models
from backend.workers.lead_sourcing import sync_leads


def build_session():
    import_models()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SessionLocal()


def test_sync_leads_imports_new_records_and_skips_duplicates() -> None:
    db = build_session()
    with patch(
        "backend.domains.leads.services.lead_service.run_lead_pipeline",
        return_value={"records_processed": 2, "records_created": 1, "lead_ids": [1]},
    ):
        result = sync_leads(db, query="test", user_id=1, limit=10)

    assert result == {"imported": 1, "skipped": 1, "verified": 1}
