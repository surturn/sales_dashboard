import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.cache import CacheBackend, build_cache_key
from backend.app.database import session_scope
from backend.domains.leads.models.lead import Lead
from backend.domains.leads.models.outreach_log import OutreachLog
from backend.services.email_sender import EmailSender
from backend.services.openai_client import OpenAIClient


def _contact_value(contact: dict, *keys: str) -> str | None:
    for key in keys:
        if key in contact and contact[key]:
            return contact[key]
        properties = contact.get("properties")
        if isinstance(properties, dict) and properties.get(key):
            return properties[key]
    return None


def upsert_lead_from_contact(db: Session, contact: dict, user_id: int | None = None) -> Lead:
    email = _contact_value(contact, "email")
    phone = _contact_value(contact, "phone", "phone_number")
    lead = None
    if email:
        lead = db.scalar(select(Lead).where(Lead.email == email))
    if lead is None and phone:
        lead = db.scalar(select(Lead).where(Lead.phone == phone))

    if lead is None:
        lead = Lead(user_id=user_id)
        db.add(lead)

    lead.external_id = _contact_value(contact, "id")
    lead.name = _contact_value(contact, "fullname", "full_name") or " ".join(
        part for part in (_contact_value(contact, "firstname", "firstName", "first_name"), _contact_value(contact, "lastname", "lastName", "last_name")) if part
    ) or None
    lead.email = email
    lead.phone = phone
    lead.first_name = _contact_value(contact, "firstname", "firstName", "first_name")
    lead.last_name = _contact_value(contact, "lastname", "lastName", "last_name")
    lead.company = _contact_value(contact, "company")
    lead.company_domain = _contact_value(contact, "website", "domain")
    lead.linkedin_url = _contact_value(contact, "linkedinbio", "linkedin_url")
    lead.title = _contact_value(contact, "jobtitle", "title")
    lead.source = "hubspot"
    lead.status = "contacted"
    db.commit()
    db.refresh(lead)
    return lead


def send_outreach_for_lead(
    db: Session,
    lead: Lead,
    user_id: int | None = None,
    openai_client: OpenAIClient | None = None,
    email_sender: EmailSender | None = None,
) -> OutreachLog:
    openai_client = openai_client or OpenAIClient()
    email_sender = email_sender or EmailSender()

    subject, body = openai_client.generate_outreach_email(
        {
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "company": lead.company,
            "title": lead.title,
        }
    )
    result = email_sender.send_email(to=lead.email or "", subject=subject, body=body)
    log = OutreachLog(
        user_id=user_id or lead.user_id,
        lead_id=lead.id,
        subject=subject,
        body=body,
        provider_message_id=result.get("provider_message_id"),
        status="sent" if result.get("success") else "failed",
    )
    db.add(log)
    lead.last_contacted_at = log.sent_at
    db.commit()
    db.refresh(log)
    CacheBackend().delete(build_cache_key("dashboard", "leads", user_id or lead.user_id or "global"))
    return log


def process_hubspot_contact(db: Session, payload: bytes | str) -> OutreachLog | None:
    data = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    contact = data.get("contact") or data
    lead = upsert_lead_from_contact(db, contact=contact)
    if not lead.email:
        return None
    return send_outreach_for_lead(db, lead=lead)


def process_hubspot_webhook(payload: bytes) -> dict[str, str]:
    with session_scope() as db:
        process_hubspot_contact(db, payload)
    return {"status": "processed"}
