import json
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.core.timeutils import elapsed_seconds
from backend.app.core.cache import CacheBackend, build_cache_key
from backend.domains.leads.services.lead_service import create_workflow_run
from backend.domains.social.models.social_post import SocialPost
from backend.domains.social.models.social_trend import SocialTrend
from backend.models.workflow_run import WorkflowRun
from backend.services.n8n_client import N8NClient


TREND_DISCOVERY_WORKFLOW_NAME = "social-trend-discovery"
TREND_DISCOVERY_ACTIVE_STATUSES = ("queued", "running")


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


def get_active_trend_discovery_run(db: Session, *, user_id: int | None) -> WorkflowRun | None:
    return db.scalar(
        select(WorkflowRun)
        .where(
            WorkflowRun.workflow_name == TREND_DISCOVERY_WORKFLOW_NAME,
            WorkflowRun.status.in_(TREND_DISCOVERY_ACTIVE_STATUSES),
            or_(WorkflowRun.user_id == user_id, WorkflowRun.user_id.is_(None)) if user_id is not None else WorkflowRun.user_id.is_(None),
        )
        .order_by(WorkflowRun.started_at.desc())
    )


def get_workflow_run_by_job_id(db: Session, job_id: str, *, user_id: int | None) -> WorkflowRun | None:
    try:
        workflow_run_id = parse_trend_job_id(job_id)
    except (TypeError, ValueError):
        return None

    if user_id is None:
        return db.scalar(select(WorkflowRun).where(WorkflowRun.id == workflow_run_id))

    return db.scalar(
        select(WorkflowRun).where(
            WorkflowRun.id == workflow_run_id,
            or_(WorkflowRun.user_id == user_id, WorkflowRun.user_id.is_(None)),
        )
    )


def update_workflow_run_payload(db: Session, run: WorkflowRun, payload: dict) -> WorkflowRun:
    existing_payload = json.loads(run.payload or "{}") if run.payload else {}
    existing_payload.update(payload)
    run.payload = json.dumps(existing_payload)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def list_trends_for_user(db: Session, user_id: int, platform: str | None = None, limit: int = 25) -> list[SocialTrend]:
    query = (
        select(SocialTrend)
        .where(or_(SocialTrend.user_id == user_id, SocialTrend.user_id.is_(None)))
        .order_by(SocialTrend.discovered_at.desc())
        .limit(limit)
    )
    if platform:
        query = query.where(SocialTrend.platform == platform)
    return list(db.scalars(query).all())


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
    cache_key = build_cache_key("social", "trends", user_id or "global", topic, ",".join(sorted(platforms)), limit)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

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
        response = client.trigger_workflow(
            settings.SOCIAL_TRENDS_WEBHOOK_PATH,
            {"topic": topic, "platforms": platforms, "limit": limit},
        )
        raw_trends = response.get("results") or response.get("trends") or []
        stored_ids: list[int] = []
        for item in raw_trends:
            platform = (item.get("platform") or "instagram").lower()
            keyword = item.get("keyword") or item.get("topic") or topic
            existing = db.scalar(
                select(SocialTrend).where(
                    SocialTrend.platform == platform,
                    SocialTrend.keyword == keyword,
                    or_(SocialTrend.user_id == user_id, SocialTrend.user_id.is_(None)),
                )
            )
            trend = existing or SocialTrend(user_id=user_id, platform=platform, keyword=keyword)
            trend.summary = item.get("summary") or item.get("description")
            trend.score = float(item.get("score") or item.get("rank") or 0.0)
            trend.source = item.get("source") or "n8n"
            trend.status = "ranked"
            trend.payload = json.dumps(item)
            db.add(trend)
            db.commit()
            db.refresh(trend)
            stored_ids.append(trend.id)

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

        result = {"topic": topic, "platforms": platforms, "trend_ids": stored_ids, "count": len(stored_ids)}
        cache.set(cache_key, result, ttl=settings.CACHE_TRENDS_TTL_SECONDS)
        return result
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        et = elapsed_seconds(run.started_at, run.completed_at)
        run.execution_time = round(et, 3) if et is not None else None
        db.add(run)
        db.commit()
        raise
