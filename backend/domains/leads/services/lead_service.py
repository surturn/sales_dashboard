import json

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.workers.lead_pipeline import run_lead_pipeline
from backend.app.core.cache import CacheBackend, build_cache_key
from backend.domains.leads.models.lead import Lead
from backend.models.workflow_run import WorkflowRun
from backend.schemas.lead import LeadCreate


def create_workflow_run(
    db: Session,
    *,
    workflow_name: str,
    domain: str,
    trigger_source: str,
    user_id: int | None,
    payload: dict | None = None,
) -> WorkflowRun:
    run = WorkflowRun(
        workflow_name=workflow_name,
        domain=domain,
        user_id=user_id,
        trigger_source=trigger_source,
        status="running",
        payload=json.dumps(payload or {}),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def list_leads_for_user(db: Session, user_id: int, status_filter: str | None = None, limit: int = 50) -> list[Lead]:
    query = (
        select(Lead)
        .where(or_(Lead.user_id == user_id, Lead.user_id.is_(None)))
        .order_by(Lead.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        query = query.where(Lead.status == status_filter)
    return list(db.scalars(query).all())


def create_lead_record(db: Session, user_id: int, lead_in: LeadCreate) -> Lead:
    payload = lead_in.model_dump()
    if not payload.get("name"):
        first_name = payload.get("first_name") or ""
        last_name = payload.get("last_name") or ""
        payload["name"] = " ".join(part for part in (first_name, last_name) if part) or None
    lead = Lead(user_id=user_id, **payload)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    CacheBackend().delete(build_cache_key("dashboard", "leads", user_id))
    return lead


def sync_discovered_leads(db: Session, query: str, user_id: int | None = None, limit: int = 25) -> dict:
    result = run_lead_pipeline(db, query=query, user_id=user_id, limit=limit)
    CacheBackend().delete(build_cache_key("dashboard", "leads", user_id or "global"))
    return {
        "imported": result["records_created"],
        "skipped": max(result["records_processed"] - result["records_created"], 0),
        "verified": result["records_created"],
    }
