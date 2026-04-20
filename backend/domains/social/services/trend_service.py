import json
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.core.timeutils import elapsed_seconds
from backend.app.core.cache import CacheBackend, build_cache_key
from backend.domains.leads.services.lead_service import create_workflow_run
from backend.domains.social.models.social_post import SocialPost
from backend.domains.social.services.content_service import generate_session_draft
from backend.models.workflow_run import WorkflowRun
from backend.services.draft_session import DraftSessionService
from backend.services.n8n_client import N8NClient


TREND_DISCOVERY_WORKFLOW_NAME = "social-trend-discovery"
TREND_DISCOVERY_ACTIVE_STATUSES = ("queued", "running")
TREND_DISCOVERY_ORPHANED_TASK_GRACE_PERIOD = timedelta(minutes=1)
TREND_DISCOVERY_STALE_PENDING_THRESHOLD = timedelta(minutes=15)


def make_trend_job_id(workflow_run_id: int) -> str:
    return f"trend_{workflow_run_id}"


def parse_trend_job_id(job_id: str) -> int:
    prefix = "trend_"
    if not job_id.startswith(prefix):
        raise ValueError("Invalid trend discovery job id")
    return int(job_id.removeprefix(prefix))


def serialize_workflow_run(run: WorkflowRun) -> dict:
    payload = json.loads(run.payload or "{}") if run.payload else {}
    execution_time = run.execution_time
    if execution_time is None and run.started_at and run.completed_at:
        et = elapsed_seconds(run.started_at, run.completed_at)
        execution_time = round(et, 3) if et is not None else None
    return {
        "job_id": make_trend_job_id(run.id) if run.workflow_name == TREND_DISCOVERY_WORKFLOW_NAME else f"workflow_{run.id}",
        "workflow_run_id": run.id,
        "workflow_name": run.workflow_name,
        "domain": run.domain,
        "status": run.status,
        "records_processed": run.records_processed,
        "records_created": run.records_created,
        "execution_time": execution_time,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_message": run.error_message,
        "payload": payload,
    }


def reconcile_trend_workflow_run(db: Session, run: WorkflowRun) -> WorkflowRun:
    if run.status not in TREND_DISCOVERY_ACTIVE_STATUSES:
        return run

    payload = json.loads(run.payload or "{}") if run.payload else {}
    task_id = payload.get("task_id")
    now = datetime.utcnow()
    run_age = now - run.started_at if run.started_at else timedelta(0)

    if not task_id:
        if run_age >= TREND_DISCOVERY_ORPHANED_TASK_GRACE_PERIOD:
            run.status = "failed"
            run.error_message = run.error_message or "Workflow run became orphaned before a task id was recorded"
            run.completed_at = run.completed_at or now
            run.execution_time = round((run.completed_at - run.started_at).total_seconds(), 3) if run.started_at else None
            db.add(run)
            db.commit()
            db.refresh(run)
        return run

    from backend.workers.celery_app import celery_app

    async_result = celery_app.AsyncResult(task_id)
    state = str(async_result.state or "").upper()

    if state in {"STARTED", "RECEIVED", "RETRY"}:
        if run.status != "running":
            run.status = "running"
    elif state == "SUCCESS":
        result = async_result.result if isinstance(async_result.result, dict) else {}
        run.status = "completed"
        run.completed_at = run.completed_at or now
        run.execution_time = round((run.completed_at - run.started_at).total_seconds(), 3) if run.started_at else None
        if result:
            run.records_processed = int(result.get("count") or run.records_processed or 0)
            run.records_created = int(result.get("count") or len(result.get("draft_ids") or []) or run.records_created or 0)
            update_workflow_run_payload(db, run, result)
            db.refresh(run)
            return run
    elif state == "FAILURE":
        run.status = "failed"
        run.error_message = str(async_result.result)
        run.completed_at = run.completed_at or now
        run.execution_time = round((run.completed_at - run.started_at).total_seconds(), 3) if run.started_at else None
    elif state == "REVOKED":
        run.status = "stopped"
        run.completed_at = run.completed_at or now
        run.execution_time = round((run.completed_at - run.started_at).total_seconds(), 3) if run.started_at else None
    elif state == "PENDING" and run_age >= TREND_DISCOVERY_STALE_PENDING_THRESHOLD:
        run.status = "failed"
        run.error_message = run.error_message or "No active worker task was found for this workflow run"
        run.completed_at = run.completed_at or now
        run.execution_time = round((run.completed_at - run.started_at).total_seconds(), 3) if run.started_at else None
    else:
        return run

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def reconcile_active_trend_discovery_runs(db: Session, *, user_id: int | None) -> list[WorkflowRun]:
    runs = list(
        db.scalars(
            select(WorkflowRun)
            .where(
                WorkflowRun.workflow_name == TREND_DISCOVERY_WORKFLOW_NAME,
                WorkflowRun.status.in_(TREND_DISCOVERY_ACTIVE_STATUSES),
                or_(WorkflowRun.user_id == user_id, WorkflowRun.user_id.is_(None)) if user_id is not None else WorkflowRun.user_id.is_(None),
            )
            .order_by(WorkflowRun.started_at.desc())
        ).all()
    )
    return [reconcile_trend_workflow_run(db, run) for run in runs]


def _build_fallback_trends(topic: str, platforms: list[str], limit: int) -> list[dict]:
    keyword_seed = " ".join(part for part in str(topic or "").split()[:3]).strip() or "Growth"
    fallback_keywords = [
        f"{keyword_seed} Playbook",
        f"{keyword_seed} Mistakes",
        f"{keyword_seed} Checklist",
        f"{keyword_seed} Trends",
        f"{keyword_seed} Ideas",
        f"{keyword_seed} Framework",
    ]
    fallback_summaries = [
        "Audience interest is rising around practical how-to content and operator insights.",
        "Comparison posts and contrarian takes are attracting higher saves and reshares.",
        "Short educational sequences are outperforming generic promotional posts this week.",
        "Founders are reacting well to behind-the-scenes growth breakdowns and examples.",
        "Carousel and thread formats are driving stronger engagement than one-line updates.",
        "Problem-solution storytelling is trending across SMB-focused creator accounts.",
    ]

    trends: list[dict] = []
    for index in range(limit):
        platform = platforms[index % len(platforms)] if platforms else "linkedin"
        trends.append(
            {
                "platform": platform,
                "keyword": fallback_keywords[index % len(fallback_keywords)],
                "summary": fallback_summaries[index % len(fallback_summaries)],
                "score": round(8.8 - (index * 0.35), 2),
                "source": "development_fallback",
            }
        )
    return trends


def get_active_trend_discovery_run(db: Session, *, user_id: int | None) -> WorkflowRun | None:
    for run in reconcile_active_trend_discovery_runs(db, user_id=user_id):
        if run.status in TREND_DISCOVERY_ACTIVE_STATUSES:
            return run
    return None


def get_workflow_run_by_job_id(db: Session, job_id: str, *, user_id: int | None) -> WorkflowRun | None:
    try:
        workflow_run_id = parse_trend_job_id(job_id)
    except (TypeError, ValueError):
        return None

    if user_id is None:
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
        return reconcile_trend_workflow_run(db, run) if run is not None else None

    run = db.scalar(
        select(WorkflowRun).where(
            WorkflowRun.id == workflow_run_id,
            or_(WorkflowRun.user_id == user_id, WorkflowRun.user_id.is_(None)),
        )
    )
    return reconcile_trend_workflow_run(db, run) if run is not None else None


def update_workflow_run_payload(db: Session, run: WorkflowRun, payload: dict) -> WorkflowRun:
    existing_payload = json.loads(run.payload or "{}") if run.payload else {}
    existing_payload.update(payload)
    run.payload = json.dumps(existing_payload)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def list_session_drafts_for_user(*, user_id: int | None = None, platform: str | None = None, limit: int = 25) -> list[dict]:
    drafts = DraftSessionService().list_drafts(user_id)
    if platform:
        drafts = [draft for draft in drafts if str(draft.get("platform") or "").lower() == platform.lower()]
    drafts.sort(key=lambda draft: str(draft.get("created_at") or ""), reverse=True)
    return drafts[:limit]


def list_trends_for_user(db: Session, user_id: int, platform: str | None = None, limit: int = 25) -> list[dict]:
    return list_session_drafts_for_user(user_id=user_id, platform=platform, limit=limit)


def list_posts_for_user(db: Session, user_id: int, platform: str | None = None, limit: int = 25) -> list[SocialPost]:
    query = (
        select(SocialPost)
        .where(or_(SocialPost.user_id == user_id, SocialPost.user_id.is_(None)))
        .order_by(SocialPost.created_at.desc())
        .limit(limit)
    )
    if platform:
        query = query.where(SocialPost.platform == platform)
    return list(db.scalars(query).all())


def discover_trends(
    db: Session,
    *,
    topic: str,
    user_id: int | None = None,
    platforms: list[str] | None = None,
    limit: int = 12,
    workflow_run_id: int | None = None,
) -> dict:
    settings = get_settings()
    cache = CacheBackend()
    platforms = platforms or settings.SOCIAL_DEFAULT_PLATFORMS

    run = None
    if workflow_run_id is not None:
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))
        if run is not None:
            run.status = "running"
            run.error_message = None
            run.completed_at = None
            db.add(run)
            db.commit()
            db.refresh(run)
    if run is None:
        run = create_workflow_run(
            db,
            workflow_name=TREND_DISCOVERY_WORKFLOW_NAME,
            domain="social",
            trigger_source="worker",
            user_id=user_id,
            payload={"topic": topic, "platforms": platforms, "limit": limit},
        )
    client = N8NClient()
    try:
        try:
            response = client.trigger_workflow(
                settings.SOCIAL_TRENDS_WEBHOOK_PATH,
                {"topic": topic, "platforms": platforms, "limit": limit},
            )
            raw_trends = response.get("results") or response.get("trends") or []
        except Exception:
            if settings.APP_ENV != "development":
                raise
            raw_trends = _build_fallback_trends(topic, platforms, limit)
        draft_service = DraftSessionService()
        stored_drafts = [
            generate_session_draft(
                signal={
                    "platform": (item.get("platform") or "instagram").lower(),
                    "topic": topic,
                    "keyword": item.get("keyword") or item.get("topic") or topic,
                    "summary": item.get("summary") or item.get("description"),
                    "score": float(item.get("score") or item.get("rank") or 0.0),
                    "source": item.get("source") or "n8n",
                    "status": "ready",
                },
                user_id=user_id,
            )
            for item in raw_trends
        ]
        stored_drafts = draft_service.store_drafts(user_id, stored_drafts)
        stored_ids = [draft["id"] for draft in stored_drafts]

        run.status = "completed"
        run.records_processed = len(raw_trends)
        run.records_created = len(stored_ids)
        run.completed_at = datetime.now(timezone.utc)
        et = elapsed_seconds(run.started_at, run.completed_at)
        run.execution_time = round(et, 3) if et is not None else None
        run.payload = json.dumps({"topic": topic, "platforms": platforms, "trend_ids": stored_ids, "count": len(stored_ids)})
        db.add(run)
        db.commit()
        cache.delete(build_cache_key("dashboard", "social", user_id or "global"))

        return {"topic": topic, "platforms": platforms, "draft_ids": stored_ids, "count": len(stored_ids)}
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        et = elapsed_seconds(run.started_at, run.completed_at)
        run.execution_time = round(et, 3) if et is not None else None
        db.add(run)
        db.commit()
        raise
