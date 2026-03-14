from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.core.dependencies import get_current_user
from backend.app.core.rate_limit import limiter
from backend.app.database import get_db
from backend.domains.leads.services.outreach_service import send_outreach_for_lead
from backend.models.lead import Lead
from backend.models.outreach_logs import OutreachLog
from backend.models.user import User
from backend.schemas.outreach import OutreachLogRead, OutreachTriggerRequest


router = APIRouter(prefix="/outreach", tags=["outreach"])


@router.get("/", response_model=list[OutreachLogRead])
@limiter.limit("60/minute")
def get_outreach_status(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[OutreachLog]:
    query = (
        select(OutreachLog)
        .where(or_(OutreachLog.user_id == current_user.id, OutreachLog.user_id.is_(None)))
        .order_by(OutreachLog.sent_at.desc())
        .limit(50)
    )
    return list(db.scalars(query).all())


@router.post("/trigger", response_model=OutreachLogRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
def trigger_outreach(
    request: Request,
    payload: OutreachTriggerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OutreachLog:
    lead = db.scalar(
        select(Lead).where(Lead.id == payload.lead_id, or_(Lead.user_id == current_user.id, Lead.user_id.is_(None)))
    )
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return send_outreach_for_lead(db, lead=lead, user_id=current_user.id)
