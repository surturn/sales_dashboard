from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from backend.app.core.dependencies import get_current_user
from backend.app.core.rate_limit import limiter
from backend.app.database import get_db
from backend.models.lead import Lead
from backend.domains.leads.services.lead_service import create_lead_record, list_leads_for_user
from backend.models.user import User
from backend.schemas.lead import LeadCreate, LeadRead


router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("/", response_model=list[LeadRead])
@limiter.limit("60/minute")
def list_leads(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Lead]:
    return list_leads_for_user(db, user_id=current_user.id, status_filter=status_filter, limit=limit)


@router.post("/", response_model=LeadRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def create_lead(
    request: Request,
    lead_in: LeadCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Lead:
    return create_lead_record(db, user_id=current_user.id, lead_in=lead_in)
