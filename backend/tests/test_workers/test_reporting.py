from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, import_models
from backend.models.lead import Lead
from backend.models.outreach_logs import OutreachLog
from backend.models.support_logs import SupportLog
from backend.models.workflow_run import WorkflowRun
from backend.domains.social.models.social_post import SocialPost
from backend.services.draft_session import DraftSessionService
from backend.workers.reporting import build_report_metrics


def build_session():
    import_models()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SessionLocal()


def test_build_report_metrics_counts_seed_data() -> None:
    db = build_session()
    db.add(Lead(email="lead@example.com", source="linkedin_google", status="new"))
    db.add(OutreachLog(status="sent", channel="email"))
    db.add(SupportLog(status="responded"))
    db.add(WorkflowRun(domain="shared", workflow_name="weekly-report", trigger_source="scheduler", status="completed"))
    DraftSessionService().store_drafts(
        None,
        [
            {
                "platform": "instagram",
                "topic": "ai marketing",
                "keyword": "ai marketing",
                "summary": "Trend signal",
                "score": 9.5,
            }
        ],
    )
    db.add(SocialPost(platform="instagram", approval_status="approved", publish_status="pending"))
    db.commit()

    metrics = build_report_metrics(db)

    assert metrics["total_leads"] == 1
    assert metrics["outreach_sent"] == 1
    assert metrics["support_responses"] == 1
    assert metrics["tracked_trends"] == 1
    assert metrics["draft_posts"] == 1
    assert metrics["successful_workflows"] == 1
