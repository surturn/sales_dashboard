from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.core.dependencies import get_current_user
from backend.app.core.rate_limit import limiter
from backend.app.database import get_db
from backend.domains.leads.services.lead_service import create_workflow_run
from backend.domains.social.services.trend_service import (
    TREND_DISCOVERY_WORKFLOW_NAME,
    get_active_trend_discovery_run,
    get_workflow_run_by_job_id,
    make_trend_job_id,
    serialize_workflow_run,
    update_workflow_run_payload,
)
from backend.domains.social.workers.analytics import collect_social_analytics_task
from backend.domains.social.workers.trends import discover_social_trends_task
from backend.models.user import User
from backend.models.workflow_run import WorkflowRun
from backend.schemas.social import TrendDiscoveryRequest
from backend.workers.lead_sourcing import source_leads_task
from backend.workers.reporting import generate_weekly_report_task
from backend.workers.support import support_followup_task
from backend.workers.celery_app import celery_app


router = APIRouter(prefix="/workflows", tags=["workflows"])


WORKFLOW_TASKS = {
    "lead-sourcing": source_leads_task,
    "weekly-report": generate_weekly_report_task,
    "support-followup": support_followup_task,
    "social-trends": discover_social_trends_task,
    "social-analytics": collect_social_analytics_task,
}


@router.get("/")
@limiter.limit("60/minute")
def list_workflows(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    recent_runs = db.scalars(
        select(WorkflowRun)
        .where(or_(WorkflowRun.user_id == current_user.id, WorkflowRun.user_id.is_(None)))
        .order_by(WorkflowRun.started_at.desc())
        .limit(20)
    ).all()
    return {
        "available": list(WORKFLOW_TASKS.keys()),
        "recent_runs": [
            {
                "id": run.id,
                "job_id": make_trend_job_id(run.id) if run.workflow_name == TREND_DISCOVERY_WORKFLOW_NAME else f"workflow_{run.id}",
                "domain": run.domain,
                "workflow_name": run.workflow_name,
                "status": run.status,
                "records_processed": run.records_processed,
                "records_created": run.records_created,
                "execution_time": run.execution_time,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "error_message": run.error_message,
            }
            for run in recent_runs
        ],
    }


@router.post("/{workflow_name}/run", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("20/minute")
def run_workflow(request: Request, workflow_name: str, current_user: User = Depends(get_current_user)) -> dict:
    task = WORKFLOW_TASKS.get(workflow_name)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown workflow")
    task.delay(user_id=current_user.id)
    return {"workflow_name": workflow_name, "status": "queued"}


@router.post("/start-trend-discovery", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("12/minute")
def start_trend_discovery(
    request: Request,
    payload: TrendDiscoveryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    running_job = get_active_trend_discovery_run(db, user_id=current_user.id)
    if running_job is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Trend discovery is already running",
                "job_id": make_trend_job_id(running_job.id),
            },
        )

    workflow_run = create_workflow_run(
        db,
        workflow_name=TREND_DISCOVERY_WORKFLOW_NAME,
        domain="social",
        trigger_source="user",
        user_id=current_user.id,
        payload={"topic": payload.topic, "platforms": payload.platforms, "limit": payload.limit},
        status="queued",
    )
    task_result = discover_social_trends_task.delay(
        topic=payload.topic,
        platforms=payload.platforms,
        limit=payload.limit,
        user_id=current_user.id,
        workflow_run_id=workflow_run.id,
    )
    update_workflow_run_payload(
        db,
        workflow_run,
        {
            "task_id": task_result.id,
            "topic": payload.topic,
            "platforms": payload.platforms,
            "limit": payload.limit,
        },
    )
    db.refresh(workflow_run)

    return {
        "status": "started",
        "job_id": make_trend_job_id(workflow_run.id),
        "workflow_run_id": workflow_run.id,
    }


@router.get("/status/{job_id}")
@limiter.limit("60/minute")
def get_workflow_status(
    request: Request,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    run = get_workflow_run_by_job_id(db, job_id, user_id=current_user.id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow job not found")

    payload = json.loads(run.payload or "{}") if run.payload else {}
    task_id = payload.get("task_id")
    if run.status in {"queued", "running"} and task_id:
        async_result = celery_app.AsyncResult(task_id)
        if async_result.state == "STARTED" and run.status != "running":
            run.status = "running"
            db.add(run)
            db.commit()
            db.refresh(run)
        elif async_result.state == "FAILURE" and run.status != "failed":
            run.status = "failed"
            run.error_message = str(async_result.result)
            run.completed_at = run.completed_at or datetime.now(timezone.utc)
            from backend.app.core.timeutils import elapsed_seconds
            et = elapsed_seconds(run.started_at, run.completed_at)
            run.execution_time = round(et, 3) if et is not None else None
            db.add(run)
            db.commit()
            db.refresh(run)
        elif async_result.state == "REVOKED" and run.status != "stopped":
            run.status = "stopped"
            run.completed_at = run.completed_at or datetime.now(timezone.utc)
            from backend.app.core.timeutils import elapsed_seconds
            et = elapsed_seconds(run.started_at, run.completed_at)
            run.execution_time = round(et, 3) if et is not None else None
            db.add(run)
            db.commit()
            db.refresh(run)

    return serialize_workflow_run(run)


@router.post("/stop/{job_id}")
@limiter.limit("12/minute")
def stop_workflow(
    request: Request,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    run = get_workflow_run_by_job_id(db, job_id, user_id=current_user.id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow job not found")
    if run.status not in {"queued", "running"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not active")

    payload = json.loads(run.payload or "{}") if run.payload else {}
    task_id = payload.get("task_id")
    if task_id:
        celery_app.control.revoke(task_id, terminate=True)

    run.status = "stopped"
    run.completed_at = datetime.now(timezone.utc)
    from backend.app.core.timeutils import elapsed_seconds
    et = elapsed_seconds(run.started_at, run.completed_at)
    run.execution_time = round(et, 3) if et is not None else None
    db.add(run)
    db.commit()
    db.refresh(run)

    return {
        "status": "stopped",
        "job_id": make_trend_job_id(run.id),
    }
