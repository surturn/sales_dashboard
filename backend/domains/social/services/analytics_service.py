import json

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.core.cache import CacheBackend, build_cache_key
from backend.domains.social.models.social_post import SocialPost
from backend.services.draft_session import DraftSessionService
from backend.services.n8n_client import N8NClient


def build_social_metrics(db: Session, user_id: int | None = None) -> dict:
    post_scope = (
        SocialPost.user_id.is_(None)
        if user_id is None
        else or_(SocialPost.user_id == user_id, SocialPost.user_id.is_(None))
    )
    session_drafts = len(DraftSessionService().list_drafts(user_id))
    approved_posts = db.scalar(select(func.count(SocialPost.id)).where(post_scope, SocialPost.approval_status == "approved")) or 0
    published_posts = (
        db.scalar(select(func.count(SocialPost.id)).where(post_scope, SocialPost.publish_status.in_(("published", "scheduled")))) or 0
    )
    return {
        "session_drafts": session_drafts,
        "approved_posts": approved_posts,
        "published_posts": published_posts,
        "tracked_trends": session_drafts,
        "draft_posts": approved_posts,
    }


def get_cached_social_dashboard(db: Session, user_id: int | None = None) -> dict:
    cache = CacheBackend()
    key = build_cache_key("dashboard", "social", user_id or "global")
    return cache.remember(key, lambda: build_social_metrics(db, user_id=user_id))


def collect_post_analytics(db: Session, *, user_id: int | None = None) -> dict:
    settings = get_settings()
    n8n_client = N8NClient()
    posts = db.scalars(
        select(SocialPost).where(
            or_(SocialPost.user_id == user_id, SocialPost.user_id.is_(None))
            if user_id is not None
            else SocialPost.user_id.is_(None)
        )
    ).all()

    updated = 0
    for post in posts:
        if not post.external_post_id:
            continue
        response = n8n_client.trigger_workflow(
            settings.SOCIAL_ANALYTICS_WEBHOOK_PATH,
            {"platform": post.platform, "external_post_id": post.external_post_id},
        )
        post.metrics_json = json.dumps(response)
        db.add(post)
        updated += 1

    db.commit()
    CacheBackend().delete(build_cache_key("dashboard", "social", user_id or "global"))
    return {"updated": updated}
