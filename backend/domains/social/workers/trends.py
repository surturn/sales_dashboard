from celery import current_task

from backend.app.config import get_settings
from backend.app.database import session_scope
from backend.domains.social.services.trend_service import discover_trends, update_workflow_run_payload
from backend.models.workflow_run import WorkflowRun
from backend.workers.celery_app import celery_app


@celery_app.task(name="backend.domains.social.workers.trends.discover_social_trends")
def discover_social_trends_task(
    topic: str | None = None,
    platforms: list[str] | None = None,
    limit: int = 12,
    user_id: int | None = None,
    workflow_run_id: int | None = None,
) -> dict:
    settings = get_settings()
    with session_scope() as db:
        if workflow_run_id is not None:
            run = db.get(WorkflowRun, workflow_run_id)
            if run is not None:
                update_workflow_run_payload(
                    db,
                    run,
                    {
                        "task_id": getattr(current_task.request, "id", None),
                    },
                )
                db.refresh(run)
                if run.status == "stopped":
                    return {"status": "stopped", "count": 0, "draft_ids": []}
        return discover_trends(
            db,
            topic=topic or settings.SOCIAL_DEFAULT_TOPIC,
            user_id=user_id,
            platforms=platforms or settings.SOCIAL_DEFAULT_PLATFORMS,
            limit=limit,
            workflow_run_id=workflow_run_id,
        )
