from backend.app.database import session_scope
from backend.domains.social.services.content_service import approve_session_draft, publish_post
from backend.workers.celery_app import celery_app


@celery_app.task(name="backend.domains.social.workers.content_pipeline.create_social_post")
def create_social_post_task(draft_id: str, user_id: int | None = None) -> dict:
    with session_scope() as db:
        post = approve_session_draft(db, draft_id=draft_id, user_id=user_id)
        return {"post_id": post.id, "status": post.approval_status}


@celery_app.task(name="backend.domains.social.workers.content_pipeline.publish_social_post")
def publish_social_post_task(post_id: int, user_id: int | None = None) -> dict:
    with session_scope() as db:
        post = publish_post(db, post_id=post_id, user_id=user_id)
        return {"post_id": post.id, "status": post.publish_status}
