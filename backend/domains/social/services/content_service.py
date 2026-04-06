import json
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.core.cache import CacheBackend, build_cache_key
from backend.domains.social.models.social_post import SocialPost
from backend.domains.social.models.social_trend import SocialTrend
from backend.services.n8n_client import N8NClient
from backend.services.openai_client import OpenAIClient


def create_post_from_trend(
    db: Session,
    *,
    trend_id: int,
    platform: str,
    user_id: int | None = None,
    openai_client: OpenAIClient | None = None,
) -> SocialPost:
    trend = db.scalar(
        select(SocialTrend).where(
            SocialTrend.id == trend_id,
            or_(SocialTrend.user_id == user_id, SocialTrend.user_id.is_(None)),
        )
    )
    if trend is None:
        raise ValueError("Trend not found")

    openai_client = openai_client or OpenAIClient()
    title, caption, content = openai_client.generate_social_post(
        topic=trend.keyword,
        platform=platform,
        context=trend.summary or "",
    )
    post = SocialPost(
        user_id=user_id or trend.user_id,
        trend_id=trend.id,
        platform=platform,
        title=title,
        caption=caption,
        content=content,
        approval_status="draft",
        publish_status="pending",
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    CacheBackend().delete(build_cache_key("dashboard", "social", user_id or trend.user_id or "global"))
    return post


def approve_post(db: Session, *, post_id: int, user_id: int | None = None) -> SocialPost:
    post = db.scalar(
        select(SocialPost).where(
            SocialPost.id == post_id,
            or_(SocialPost.user_id == user_id, SocialPost.user_id.is_(None)),
        )
    )
    if post is None:
        raise ValueError("Post not found")
    post.approval_status = "approved"
    db.add(post)
    db.commit()
    db.refresh(post)
    CacheBackend().delete(build_cache_key("dashboard", "social", user_id or post.user_id or "global"))
    return post


def publish_post(
    db: Session,
    *,
    post_id: int,
    user_id: int | None = None,
    schedule_for: datetime | None = None,
    n8n_client: N8NClient | None = None,
) -> SocialPost:
    post = db.scalar(
        select(SocialPost).where(
            SocialPost.id == post_id,
            or_(SocialPost.user_id == user_id, SocialPost.user_id.is_(None)),
        )
    )
    if post is None:
        raise ValueError("Post not found")
    if post.approval_status != "approved":
        raise ValueError("Post must be approved before publishing")

    settings = get_settings()
    n8n_client = n8n_client or N8NClient()
    response = n8n_client.trigger_workflow(
        settings.SOCIAL_PUBLISH_WEBHOOK_PATH,
        {
            "platform": post.platform,
            "title": post.title,
            "caption": post.caption,
            "content": post.content,
            "schedule_for": schedule_for.isoformat() if schedule_for else None,
        },
    )
    post.publish_status = "scheduled" if schedule_for else "published"
    post.scheduled_for = schedule_for
    post.published_at = None if schedule_for else datetime.now(timezone.utc)
    post.external_post_id = response.get("id") or response.get("post_id")
    post.metrics_json = json.dumps(response)
    db.add(post)
    db.commit()
    db.refresh(post)
    CacheBackend().delete(build_cache_key("dashboard", "social", user_id or post.user_id or "global"))
    return post
