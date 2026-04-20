import json
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.core.cache import CacheBackend, build_cache_key
from backend.domains.social.models.social_post import SocialPost
from backend.services.draft_session import DraftSessionService
from backend.services.n8n_client import N8NClient
from backend.services.openai_client import OpenAIClient


def _build_social_generation_context(signal: dict) -> str:
    context_parts = [
        f"Platform signal: {signal.get('platform') or 'social'}",
        f"Trend score: {signal.get('score') or 0}",
        f"Trend summary: {signal.get('summary') or 'No extra summary provided.'}",
    ]
    if signal.get("source"):
        context_parts.append(f"Source: {signal['source']}")
    if signal.get("status"):
        context_parts.append(f"Trend status: {signal['status']}")
    return " | ".join(context_parts)


def _build_fallback_post_copy(*, topic: str, platform: str, context: str) -> tuple[str, str, str]:
    normalized_platform = (platform or "social").strip().title()
    focus_line = context.strip() or f"{topic} is showing early audience interest, but the evidence should still be tested."
    title = f"{normalized_platform} {topic.title()} Brief"
    caption = f"{topic.title()} is worth watching, but only if the signal matches your audience and offer."
    content = (
        f"Hook:\n{topic.title()} is gaining attention, but attention alone is not a strategy.\n\n"
        f"Grounded insight:\n{focus_line}\n\n"
        "Critical take:\nTreat this as a signal to test, not proof that the idea will convert for your audience.\n\n"
        "Trustworthy advice:\nUse one concrete example, explain why the pattern matters now, and make one clear recommendation your audience can act on this week."
    )
    return title, caption, content


def _build_fallback_publish_response(*, post: SocialPost, schedule_for: datetime | None) -> dict:
    status = "scheduled" if schedule_for else "published"
    return {
        "id": f"dev-{post.platform}-{post.id}",
        "status": status,
        "scheduled_for": schedule_for.isoformat() if schedule_for else None,
        "source": "development_fallback",
    }


def generate_session_draft(
    *,
    signal: dict,
    user_id: int | None = None,
    openai_client: OpenAIClient | None = None,
) -> dict:
    topic = str(signal.get("keyword") or signal.get("topic") or "social idea").strip()
    platform = str(signal.get("platform") or "social").strip().lower()
    trend_context = _build_social_generation_context(signal)
    settings = get_settings()
    openai_client = openai_client or OpenAIClient()
    try:
        title, caption, content = openai_client.generate_social_post(
            topic=topic,
            platform=platform,
            context=trend_context,
        )
    except Exception:
        if settings.APP_ENV != "development":
            raise
        title, caption, content = _build_fallback_post_copy(
            topic=topic,
            platform=platform,
            context=trend_context,
        )

    return DraftSessionService().seed_draft(
        {
            "user_id": user_id,
            "platform": platform,
            "topic": str(signal.get("topic") or topic),
            "keyword": topic,
            "summary": signal.get("summary"),
            "score": signal.get("score"),
            "source": signal.get("source") or "n8n",
            "status": signal.get("status") or "draft",
            "title": title,
            "caption": caption,
            "content": content,
        }
    )


def approve_session_draft(
    db: Session,
    *,
    draft_id: str,
    user_id: int | None = None,
) -> SocialPost:
    draft_service = DraftSessionService()
    draft = draft_service.pop_draft(user_id, draft_id)
    if draft is None:
        raise ValueError("Draft not found")

    post = SocialPost(
        user_id=user_id,
        trend_id=None,
        platform=str(draft.get("platform") or "social"),
        title=draft.get("title"),
        caption=draft.get("caption"),
        content=draft.get("content"),
        approval_status="approved",
        publish_status="pending",
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    CacheBackend().delete(build_cache_key("dashboard", "social", user_id or "global"))
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


def discard_session_draft(*, draft_id: str, user_id: int | None = None) -> None:
    removed = DraftSessionService().remove_draft(user_id, draft_id)
    if not removed:
        raise ValueError("Draft not found")
    CacheBackend().delete(build_cache_key("dashboard", "social", user_id or "global"))


def discard_post(db: Session, *, post_id: int, user_id: int | None = None) -> None:
    post = db.scalar(
        select(SocialPost).where(
            SocialPost.id == post_id,
            or_(SocialPost.user_id == user_id, SocialPost.user_id.is_(None)),
        )
    )
    if post is None:
        raise ValueError("Post not found")
    if post.publish_status == "published":
        raise ValueError("Published posts cannot be discarded")

    cache_user_id = user_id or post.user_id or "global"
    db.delete(post)
    db.commit()
    CacheBackend().delete(build_cache_key("dashboard", "social", cache_user_id))


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
    try:
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
    except Exception:
        if settings.APP_ENV != "development":
            raise
        response = _build_fallback_publish_response(post=post, schedule_for=schedule_for)
    post.publish_status = "scheduled" if schedule_for else "published"
    post.scheduled_for = schedule_for
    post.published_at = None if schedule_for else datetime.utcnow()
    post.external_post_id = response.get("id") or response.get("post_id")
    post.metrics_json = json.dumps(response)
    db.add(post)
    db.commit()
    db.refresh(post)
    CacheBackend().delete(build_cache_key("dashboard", "social", user_id or post.user_id or "global"))
    return post
