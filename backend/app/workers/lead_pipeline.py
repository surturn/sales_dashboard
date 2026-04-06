import json
import time
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.core.cache import CacheBackend, build_cache_key
from backend.app.workers.company_parser import parse_company_profiles
from backend.app.workers.company_scraper import scrape_companies
from backend.app.workers.email_pattern_generator import generate_email_candidates
from backend.app.workers.email_verifier import verify_email_candidates
from backend.app.workers.linkedin_scraper import discover_company_contacts
from backend.domains.leads.models.lead import Lead
from backend.models.workflow_run import WorkflowRun
from backend.services.hubspot import HubSpotClient


def chunk(items: list[dict], size: int) -> Iterable[list[dict]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def run_lead_pipeline(db: Session, query: str, user_id: int | None = None, limit: int = 20) -> dict:
    settings = get_settings()
    started_at = time.perf_counter()
    workflow_run = WorkflowRun(
        workflow_name="lead-sourcing",
        domain="leads",
        user_id=user_id,
        trigger_source="worker",
        status="running",
        records_processed=0,
        records_created=0,
        payload=json.dumps({"query": query, "limit": limit}),
    )
    db.add(workflow_run)
    db.commit()
    db.refresh(workflow_run)

    existing_emails = {email for email in db.scalars(select(Lead.email).where(Lead.email.is_not(None))).all()}
    records_processed = 0
    records_created = 0
    created_leads: list[Lead] = []
    hubspot = HubSpotClient()

    try:
        companies = scrape_companies(query=query, limit=limit)
        for company_batch in chunk(companies, settings.LEAD_PIPELINE_BATCH_SIZE):
            parsed_companies = parse_company_profiles(company_batch)
            contacts = discover_company_contacts(parsed_companies)
            generated = generate_email_candidates(contacts)
            verified = verify_email_candidates(generated)

            batch_to_store: list[Lead] = []
            for candidate in verified:
                records_processed += 1
                email = candidate.get("email")
                if not email or email in existing_emails:
                    continue

                existing_emails.add(email)
                lead = Lead(
                    user_id=user_id,
                    external_id=candidate.get("source_url") or candidate.get("linkedin_company_url"),
                    name=candidate.get("name"),
                    email=email,
                    phone=candidate.get("phone"),
                    first_name=candidate.get("first_name"),
                    last_name=candidate.get("last_name"),
                    company=candidate.get("company") or candidate.get("company_name"),
                    company_domain=candidate.get("company_domain"),
                    linkedin_url=candidate.get("source_url") or candidate.get("linkedin_company_url"),
                    title=candidate.get("title"),
                    source="google_maps_pipeline",
                    status="verified",
                )
                batch_to_store.append(lead)

            if batch_to_store:
                db.add_all(batch_to_store)
                db.commit()
                hubspot_payloads: list[dict] = []
                for lead in batch_to_store:
                    db.refresh(lead)
                    created_leads.append(lead)
                    records_created += 1
                    if lead.email:
                        hubspot_payloads.append(
                            {
                                "email": lead.email,
                                "firstname": lead.first_name,
                                "lastname": lead.last_name,
                                "company": lead.company,
                                "website": lead.company_domain,
                                "jobtitle": lead.title,
                            }
                        )
                if hubspot_payloads:
                    hubspot.batch_upsert_contacts(hubspot_payloads)

        workflow_run.status = "completed"
        workflow_run.records_processed = records_processed
        workflow_run.records_created = records_created
        workflow_run.execution_time = round(time.perf_counter() - started_at, 3)
        workflow_run.completed_at = datetime.now(timezone.utc)
        workflow_run.payload = json.dumps(
            {
                "query": query,
                "limit": limit,
                "records_processed": records_processed,
                "records_created": records_created,
                "lead_ids": [lead.id for lead in created_leads],
            }
        )
        db.add(workflow_run)
        db.commit()
        CacheBackend().delete(build_cache_key("dashboard", "leads", user_id or "global"))
        return {
            "records_processed": records_processed,
            "records_created": records_created,
            "lead_ids": [lead.id for lead in created_leads],
        }
    except Exception as exc:
        workflow_run.status = "failed"
        workflow_run.records_processed = records_processed
        workflow_run.records_created = records_created
        workflow_run.execution_time = round(time.perf_counter() - started_at, 3)
        workflow_run.error_message = str(exc)
        workflow_run.completed_at = datetime.now(timezone.utc)
        db.add(workflow_run)
        db.commit()
        raise
