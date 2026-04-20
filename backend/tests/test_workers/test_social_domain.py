from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.cache import CacheBackend, build_cache_key
from backend.models import Base, import_models
from backend.domains.social.models.social_post import SocialPost
from backend.domains.social.services.content_service import (
    approve_session_draft,
    discard_post,
    discard_session_draft,
    generate_session_draft,
    publish_post,
)
from backend.domains.social.services.trend_service import discover_trends
from backend.services.draft_session import DraftSessionService


def build_session():
    import_models()
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SessionLocal()


def test_discover_trends_stores_session_drafts_only() -> None:
    db = build_session()
    CacheBackend().delete(build_cache_key("dashboard", "social", 1))
    fake_n8n = Mock()
    fake_n8n.trigger_workflow.return_value = {
        "trends": [
            {"platform": "instagram", "keyword": "ai sales", "summary": "Fast-rising topic", "score": 8.9}
        ]
    }
    fake_openai = Mock()
    fake_openai.generate_social_post.return_value = ("AI Sales Hook", "Short caption", "Longer body")

    with (
        patch("backend.domains.social.services.trend_service.N8NClient", return_value=fake_n8n),
        patch("backend.domains.social.services.content_service.OpenAIClient", return_value=fake_openai),
    ):
        result = discover_trends(db, topic="ai sales test", user_id=1, platforms=["instagram"], limit=5)

    assert result["count"] == 1
    assert len(result["draft_ids"]) == 1
    drafts = DraftSessionService().list_drafts(1)
    assert len(drafts) == 1
    assert drafts[0]["keyword"] == "ai sales"
    assert db.query(SocialPost).count() == 0


def test_approve_session_draft_persists_post() -> None:
    db = build_session()
    draft_service = DraftSessionService()
    draft = draft_service.seed_draft(
        {
            "platform": "instagram",
            "topic": "ai sales",
            "keyword": "ai sales",
            "summary": "Helpful summary",
            "score": 8.0,
            "title": "AI Sales Hook",
            "caption": "Short caption",
            "content": "Longer body",
        }
    )
    draft_service.store_drafts(1, [draft])

    post = approve_session_draft(db, draft_id=draft["id"], user_id=1)

    assert post.approval_status == "approved"
    assert db.query(SocialPost).count() == 1
    assert DraftSessionService().list_drafts(1) == []


def test_generate_session_draft_falls_back_in_development() -> None:
    db = build_session()
    fake_openai = Mock()
    fake_openai.generate_social_post.side_effect = RuntimeError("quota exceeded")

    with patch("backend.domains.social.services.content_service.OpenAIClient", return_value=fake_openai):
        draft = generate_session_draft(
            signal={
                "platform": "linkedin",
                "topic": "pipeline review",
                "keyword": "pipeline review",
                "summary": "Useful operator context",
                "score": 7.4,
                "source": "test",
                "status": "ready",
            },
            user_id=1,
        )

    assert draft["title"]
    assert "pipeline review" in (draft["caption"] or "").lower()
    assert "Critical take:" in (draft["content"] or "")
    assert "Trustworthy advice:" in (draft["content"] or "")
    assert db.query(SocialPost).count() == 0


def test_publish_post_falls_back_in_development() -> None:
    db = build_session()
    post = SocialPost(
        user_id=1,
        platform="instagram",
        title="Draft title",
        caption="Draft caption",
        content="Draft body",
        approval_status="approved",
        publish_status="pending",
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    fake_n8n = Mock()
    fake_n8n.trigger_workflow.side_effect = RuntimeError("workflow missing")

    published = publish_post(db, post_id=post.id, user_id=1, n8n_client=fake_n8n)

    assert published.publish_status == "published"
    assert str(published.external_post_id).startswith("dev-instagram-")


def test_discard_session_draft_removes_cached_draft() -> None:
    draft_service = DraftSessionService()
    draft = draft_service.seed_draft(
        {
            "platform": "instagram",
            "topic": "founder content",
            "keyword": "founder content",
            "summary": "Useful summary",
            "score": 7.8,
        }
    )
    draft_service.store_drafts(1, [draft])

    discard_session_draft(draft_id=draft["id"], user_id=1)

    assert DraftSessionService().list_drafts(1) == []


def test_discard_post_rejects_published_post() -> None:
    db = build_session()
    post = SocialPost(
        user_id=1,
        platform="instagram",
        title="Published title",
        caption="Published caption",
        content="Published body",
        approval_status="approved",
        publish_status="published",
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    try:
        discard_post(db, post_id=post.id, user_id=1)
    except ValueError as exc:
        assert str(exc) == "Published posts cannot be discarded"
    else:
        raise AssertionError("Expected discard_post to reject published posts")
