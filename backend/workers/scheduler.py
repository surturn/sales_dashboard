from backend.domains.social.workers.analytics import collect_social_analytics_task
from backend.domains.social.workers.trends import discover_social_trends_task
from backend.workers.lead_sourcing import source_leads_task
from backend.workers.reporting import generate_weekly_report_task


def trigger_lead_sourcing(query: str, user_id: int | None = None):
    return source_leads_task.delay(query=query, user_id=user_id)


def trigger_weekly_report():
    return generate_weekly_report_task.delay()


def trigger_social_trends(topic: str, user_id: int | None = None):
    return discover_social_trends_task.delay(topic=topic, user_id=user_id)


WORKFLOW_DISPATCH = {
    "lead-sourcing": source_leads_task,
    "weekly-report": generate_weekly_report_task,
    "social-trends": discover_social_trends_task,
    "social-analytics": collect_social_analytics_task,
}
