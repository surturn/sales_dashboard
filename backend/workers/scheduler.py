from backend.domains.social.workers.analytics import collect_social_analytics_task
from backend.domains.social.workers.trends import discover_social_trends_task
from backend.workers.hubspot_sync_contacts import sync_hubspot_contacts_task
from backend.workers.hubspot_sync_deals import sync_hubspot_companies_task, sync_hubspot_deals_task
from backend.workers.lead_sourcing import source_leads_task
from backend.workers.reporting import generate_weekly_report_task

# Try agent entrypoints first (minimal reversible stubs). If agents return
# False or raise, we fall back to the existing Celery tasks.
from backend.app.agents.entrypoints import try_run_lead_sourcing, try_run_weekly_report


def trigger_lead_sourcing(query: str, user_id: int | None = None):
    handled = try_run_lead_sourcing(query=query, user_id=user_id)
    if handled:
        return {"status": "agent_handled"}
    return source_leads_task.delay(query=query, user_id=user_id)


def trigger_weekly_report():
    handled = try_run_weekly_report()
    if handled:
        return {"status": "agent_handled"}
    return generate_weekly_report_task.delay()


def trigger_social_trends(topic: str, user_id: int | None = None):
    return discover_social_trends_task.delay(topic=topic, user_id=user_id)


def trigger_hubspot_contact_sync(user_id: int | None = None):
    return sync_hubspot_contacts_task.delay(user_id=user_id)


def trigger_hubspot_deal_sync(user_id: int | None = None):
    return sync_hubspot_deals_task.delay(user_id=user_id)


def trigger_hubspot_company_sync(user_id: int | None = None):
    return sync_hubspot_companies_task.delay(user_id=user_id)


WORKFLOW_DISPATCH = {
    "lead-sourcing": source_leads_task,
    "weekly-report": generate_weekly_report_task,
    "social-trends": discover_social_trends_task,
    "social-analytics": collect_social_analytics_task,
    "hubspot-contact-sync": sync_hubspot_contacts_task,
    "hubspot-deal-sync": sync_hubspot_deals_task,
    "hubspot-company-sync": sync_hubspot_companies_task,
}
