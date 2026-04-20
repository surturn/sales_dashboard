from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from backend.app.core.cache import CacheBackend, build_cache_key
from backend.domains.leads.models.lead import Lead
from backend.domains.leads.services.lead_service import create_workflow_run
from backend.domains.leads.services.outreach_service import upsert_lead_from_contact
from backend.models.sync_state import SyncState
from backend.models.workflow_run import WorkflowRun
from backend.services.hubspot import HubSpotClient


def _parse_hubspot_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized.replace(tzinfo=None)
    text_value = str(value).strip()
    if text_value.isdigit():
        try:
            return datetime.fromtimestamp(int(text_value) / 1000, tz=UTC).replace(tzinfo=None)
        except (TypeError, ValueError, OSError):
            return None
    try:
        return datetime.fromisoformat(text_value.replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)
    except ValueError:
        return None


def _normalize_sync_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _complete_run(
    db: Session,
    run: WorkflowRun,
    *,
    status: str,
    records_processed: int,
    records_created: int,
    payload: dict[str, Any],
    error_message: str | None = None,
) -> None:
    run.status = status
    run.records_processed = records_processed
    run.records_created = records_created
    run.completed_at = datetime.utcnow()
    run.execution_time = round((run.completed_at - run.started_at).total_seconds(), 3) if run.started_at else None
    run.payload = json.dumps(payload)
    run.error_message = error_message
    db.add(run)
    db.commit()


def get_sync_state(db: Session) -> SyncState:
    state = db.scalar(select(SyncState).where(SyncState.id == 1))
    if state is None:
        state = SyncState(id=1)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _existing_lead_for_contact(db: Session, contact: dict[str, Any]) -> Lead | None:
    properties = contact.get("properties", {}) if isinstance(contact.get("properties"), dict) else {}
    contact_id = str(contact.get("id") or properties.get("hs_object_id") or "")
    email = properties.get("email") or contact.get("email")
    phone = properties.get("phone") or contact.get("phone")

    if contact_id:
        existing = db.scalar(select(Lead).where(Lead.external_id == contact_id))
        if existing is not None:
            return existing
    if email:
        existing = db.scalar(select(Lead).where(Lead.email == email))
        if existing is not None:
            return existing
    if phone:
        existing = db.scalar(select(Lead).where(Lead.phone == phone))
        if existing is not None:
            return existing
    return None


def _invalidate_hubspot_cache(user_id: int | None = None) -> None:
    cache = CacheBackend()
    scope = user_id or "global"
    cache.delete(build_cache_key("dashboard", "leads", scope))
    cache.delete(build_cache_key("hubspot", "metrics", scope))
    cache.delete(build_cache_key("hubspot", "leads", scope, 8))
    cache.delete(build_cache_key("hubspot", "opportunities", scope))
    cache.delete(build_cache_key("hubspot", "sales", scope))
    cache.delete(build_cache_key("hubspot", "tasks", scope))


def _fetch_paginated(fetch_page, *, updated_after: datetime | None, page_limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        payload = fetch_page(limit=page_limit, after=after, updated_after=updated_after)
        items.extend(payload.get("results", []))
        after = (
            payload.get("paging", {})
            .get("next", {})
            .get("after")
        )
        if not after:
            break
    return items


def sync_contacts_incremental(
    db: Session,
    *,
    user_id: int | None = None,
    object_ids: list[str] | None = None,
    page_limit: int = 100,
    trigger_source: str = "scheduler",
    client: HubSpotClient | None = None,
) -> dict[str, Any]:
    client = client or HubSpotClient()
    sync_state = get_sync_state(db)
    last_sync_before = _normalize_sync_timestamp(sync_state.last_contact_sync)
    run = create_workflow_run(
        db,
        workflow_name="hubspot-contact-sync",
        domain="leads",
        trigger_source=trigger_source,
        user_id=user_id,
        payload={"object_ids": object_ids or [], "last_sync_before": last_sync_before.isoformat() if last_sync_before else None},
    )

    processed = 0
    created = 0
    max_seen_timestamp = last_sync_before
    synced_ids: list[int] = []

    try:
        records = (
            client.batch_read_contacts(object_ids).get("results", [])
            if object_ids
            else _fetch_paginated(client.list_contacts, updated_after=last_sync_before, page_limit=page_limit)
        )

        for contact in records:
            processed += 1
            before = _existing_lead_for_contact(db, contact)
            lead = upsert_lead_from_contact(db, contact=contact, user_id=user_id)
            if before is None:
                created += 1
            synced_ids.append(lead.id)
            modified_at = _parse_hubspot_datetime(
                (contact.get("properties") or {}).get("hs_lastmodifieddate")
                or (contact.get("properties") or {}).get("createdate")
            )
            if modified_at and (max_seen_timestamp is None or modified_at > max_seen_timestamp):
                max_seen_timestamp = modified_at

        sync_state.last_contact_sync = _normalize_sync_timestamp(max_seen_timestamp) or datetime.utcnow()
        db.add(sync_state)
        db.commit()
        _complete_run(
            db,
            run,
            status="completed",
            records_processed=processed,
            records_created=created,
            payload={
                "synced_ids": synced_ids,
                "last_sync_after": sync_state.last_contact_sync.isoformat() if sync_state.last_contact_sync else None,
            },
        )
        _invalidate_hubspot_cache(user_id)
        return {
            "records_processed": processed,
            "records_created": created,
            "last_sync_timestamp": sync_state.last_contact_sync.isoformat() if sync_state.last_contact_sync else None,
        }
    except Exception as exc:
        _complete_run(
            db,
            run,
            status="failed",
            records_processed=processed,
            records_created=created,
            payload={"object_ids": object_ids or []},
            error_message=str(exc),
        )
        raise


def sync_deals_incremental(
    db: Session,
    *,
    user_id: int | None = None,
    object_ids: list[str] | None = None,
    page_limit: int = 100,
    trigger_source: str = "scheduler",
    client: HubSpotClient | None = None,
) -> dict[str, Any]:
    client = client or HubSpotClient()
    sync_state = get_sync_state(db)
    last_sync_before = _normalize_sync_timestamp(sync_state.last_deal_sync)
    run = create_workflow_run(
        db,
        workflow_name="hubspot-deal-sync",
        domain="leads",
        trigger_source=trigger_source,
        user_id=user_id,
        payload={"object_ids": object_ids or [], "last_sync_before": last_sync_before.isoformat() if last_sync_before else None},
    )

    processed = 0
    max_seen_timestamp = last_sync_before
    deal_summaries: list[dict[str, Any]] = []

    try:
        records = (
            client.batch_read_deals(object_ids).get("results", [])
            if object_ids
            else _fetch_paginated(client.list_deals, updated_after=last_sync_before, page_limit=page_limit)
        )

        for deal in records:
            processed += 1
            properties = deal.get("properties", {}) if isinstance(deal.get("properties"), dict) else {}
            deal_summaries.append(
                {
                    "id": str(deal.get("id")),
                    "name": properties.get("dealname"),
                    "stage": properties.get("dealstage"),
                    "amount": properties.get("amount"),
                }
            )
            modified_at = _parse_hubspot_datetime(properties.get("hs_lastmodifieddate") or properties.get("createdate"))
            if modified_at and (max_seen_timestamp is None or modified_at > max_seen_timestamp):
                max_seen_timestamp = modified_at

        sync_state.last_deal_sync = _normalize_sync_timestamp(max_seen_timestamp) or datetime.utcnow()
        db.add(sync_state)
        db.commit()
        _complete_run(
            db,
            run,
            status="completed",
            records_processed=processed,
            records_created=0,
            payload={
                "deals": deal_summaries,
                "last_sync_after": sync_state.last_deal_sync.isoformat() if sync_state.last_deal_sync else None,
            },
        )
        _invalidate_hubspot_cache(user_id)
        return {
            "records_processed": processed,
            "records_created": 0,
            "last_sync_timestamp": sync_state.last_deal_sync.isoformat() if sync_state.last_deal_sync else None,
        }
    except Exception as exc:
        _complete_run(
            db,
            run,
            status="failed",
            records_processed=processed,
            records_created=0,
            payload={"object_ids": object_ids or []},
            error_message=str(exc),
        )
        raise


def sync_companies_incremental(
    db: Session,
    *,
    user_id: int | None = None,
    page_limit: int = 100,
    trigger_source: str = "scheduler",
    client: HubSpotClient | None = None,
) -> dict[str, Any]:
    client = client or HubSpotClient()
    sync_state = get_sync_state(db)
    last_sync_before = _normalize_sync_timestamp(sync_state.last_company_sync)
    run = create_workflow_run(
        db,
        workflow_name="hubspot-company-sync",
        domain="leads",
        trigger_source=trigger_source,
        user_id=user_id,
        payload={"last_sync_before": last_sync_before.isoformat() if last_sync_before else None},
    )

    processed = 0
    max_seen_timestamp = last_sync_before

    try:
        records = _fetch_paginated(client.list_companies, updated_after=last_sync_before, page_limit=page_limit)
        for company in records:
            processed += 1
            properties = company.get("properties", {}) if isinstance(company.get("properties"), dict) else {}
            modified_at = _parse_hubspot_datetime(properties.get("hs_lastmodifieddate") or properties.get("createdate"))
            if modified_at and (max_seen_timestamp is None or modified_at > max_seen_timestamp):
                max_seen_timestamp = modified_at

        sync_state.last_company_sync = _normalize_sync_timestamp(max_seen_timestamp) or datetime.utcnow()
        db.add(sync_state)
        db.commit()
        _complete_run(
            db,
            run,
            status="completed",
            records_processed=processed,
            records_created=0,
            payload={"last_sync_after": sync_state.last_company_sync.isoformat() if sync_state.last_company_sync else None},
        )
        return {
            "records_processed": processed,
            "records_created": 0,
            "last_sync_timestamp": sync_state.last_company_sync.isoformat() if sync_state.last_company_sync else None,
        }
    except Exception as exc:
        _complete_run(
            db,
            run,
            status="failed",
            records_processed=processed,
            records_created=0,
            payload={},
            error_message=str(exc),
        )
        raise


def delete_contact_records(db: Session, object_ids: list[str]) -> dict[str, int]:
    if not object_ids:
        return {"deleted": 0}
    deleted = db.query(Lead).filter(Lead.external_id.in_([str(object_id) for object_id in object_ids])).delete(synchronize_session=False)
    db.commit()
    _invalidate_hubspot_cache()
    return {"deleted": int(deleted)}


def record_deal_deletions(db: Session, object_ids: list[str], *, user_id: int | None = None) -> dict[str, Any]:
    run = create_workflow_run(
        db,
        workflow_name="hubspot-deal-delete",
        domain="leads",
        trigger_source="webhook",
        user_id=user_id,
        payload={"object_ids": object_ids},
    )
    _complete_run(
        db,
        run,
        status="completed",
        records_processed=len(object_ids),
        records_created=0,
        payload={"deleted_object_ids": object_ids},
    )
    _invalidate_hubspot_cache(user_id)
    return {"deleted": len(object_ids)}
