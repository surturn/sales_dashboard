from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.cache import CacheBackend, build_cache_key
from backend.models import Base, import_models
from backend.domains.social.models.social_post import SocialPost
from backend.domains.social.models.social_trend import SocialTrend
from backend.domains.social.services.content_service import approve_post, create_post_from_trend
from backend.domains.social.services.trend_service import discover_trends


def build_session():
    import_models()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SessionLocal()


def test_discover_trends_stores_results() -> None:
    db = build_session()
    CacheBackend().delete(build_cache_key("social", "trends", 1, "ai sales test", "instagram", 5))
    fake_n8n = Mock()
    fake_n8n.trigger_workflow.return_value = {
        "trends": [
            {"platform": "instagram", "keyword": "ai sales", "summary": "Fast-rising topic", "score": 8.9}
        ]
    }

    with patch("backend.domains.social.services.trend_service.N8NClient", return_value=fake_n8n):
        result = discover_trends(db, topic="ai sales test", user_id=1, platforms=["instagram"], limit=5)

    assert result["count"] == 1
    assert db.query(SocialTrend).count() == 1


def test_create_post_from_trend_generates_draft() -> None:
    db = build_session()
    trend = SocialTrend(user_id=1, platform="instagram", keyword="ai sales", summary="Helpful summary", score=8.0)
    db.add(trend)
    db.commit()
    db.refresh(trend)

    fake_openai = Mock()
    fake_openai.generate_social_post.return_value = ("AI Sales Hook", "Short caption", "Longer body")

    with patch("backend.domains.social.services.content_service.OpenAIClient", return_value=fake_openai):
        post = create_post_from_trend(db, trend_id=trend.id, platform="instagram", user_id=1)

    approved = approve_post(db, post_id=post.id, user_id=1)
    assert approved.approval_status == "approved"
    assert db.query(SocialPost).count() == 1
