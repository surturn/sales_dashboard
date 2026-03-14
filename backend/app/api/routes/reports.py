from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.core.dependencies import get_current_user
from backend.app.database import get_db
from backend.domains.leads.services.analytics_service import get_cached_lead_dashboard
from backend.domains.social.services.analytics_service import get_cached_social_dashboard
from backend.models.user import User
from backend.models.workflow_run import WorkflowRun


router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/")
def get_reports(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    lead_metrics = get_cached_lead_dashboard(db, user_id=current_user.id)
    social_metrics = get_cached_social_dashboard(db, user_id=current_user.id)
    return {
        "totals": {
            **lead_metrics,
            **social_metrics,
        },
        "recent_reports": [
            {
                "id": run.id,
                "domain": run.domain,
                "status": run.status,
                "records_processed": run.records_processed,
                "records_created": run.records_created,
                "execution_time": run.execution_time,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "payload": run.payload,
            }
            for run in db.scalars(
                select(WorkflowRun)
                .where(
                    or_(WorkflowRun.user_id == current_user.id, WorkflowRun.user_id.is_(None)),
                    WorkflowRun.workflow_name.in_(("weekly-report", "social-trend-discovery", "social-analytics")),
                )
                .order_by(WorkflowRun.started_at.desc())
                .limit(10)
            ).all()
        ],
    }
