from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.core.dependencies import get_current_user
from backend.app.database import get_db
from backend.domains.leads.services.analytics_service import get_cached_lead_dashboard
from backend.domains.social.services.analytics_service import get_cached_social_dashboard
from backend.models.user import User
from backend.models.workflow_run import WorkflowRun


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/")
def get_dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workflow_scope = or_(WorkflowRun.user_id == current_user.id, WorkflowRun.user_id.is_(None))
    lead_metrics = get_cached_lead_dashboard(db, user_id=current_user.id)
    social_metrics = get_cached_social_dashboard(db, user_id=current_user.id)
    recent_workflows = db.scalars(
        select(WorkflowRun).where(workflow_scope).order_by(WorkflowRun.started_at.desc()).limit(5)
    ).all()

    return {
        "kpis": {
            **lead_metrics,
            **social_metrics,
        },
        "recent_workflows": [
            {
                "id": run.id,
                "domain": run.domain,
                "workflow_name": run.workflow_name,
                "status": run.status,
                "records_processed": run.records_processed,
                "records_created": run.records_created,
                "execution_time": run.execution_time,
                "started_at": run.started_at.isoformat(),
            }
            for run in recent_workflows
        ],
    }
