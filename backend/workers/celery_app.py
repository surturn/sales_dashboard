from importlib.util import find_spec

from celery import Celery
from celery.schedules import crontab

from backend.app.config import get_settings


settings = get_settings()

celery_app = Celery(
    "bizard_leads",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "backend.workers.lead_sourcing",
        "backend.workers.outreach",
        "backend.workers.support",
        "backend.workers.reporting",
        "backend.workers.scheduler",
        "backend.workers.webhook_dispatcher",
        "backend.workers.hubspot_sync_contacts",
        "backend.workers.hubspot_sync_deals",
        "backend.domains.social.workers.trends",
        "backend.domains.social.workers.content_pipeline",
        "backend.domains.social.workers.analytics",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=settings.TASKS_ALWAYS_EAGER,
    task_eager_propagates=True,
)

if find_spec("redbeat") is not None:
    celery_app.conf.update(
        beat_scheduler="redbeat.RedBeatScheduler",
        redbeat_redis_url=settings.REDIS_URL,
    )

celery_app.conf.beat_schedule = {
    "weekly-report": {
        "task": "backend.workers.scheduler.trigger_weekly_report",
        "schedule": crontab(day_of_week="mon", hour=9, minute=0),
    },
    "daily-lead-sourcing": {
        "task": "backend.workers.scheduler.trigger_lead_sourcing",
        "schedule": crontab(hour=3, minute=0),
    },
    "social-trend-discovery": {
        "task": "backend.domains.social.workers.trends.discover_social_trends",
        "schedule": crontab(day_of_week="mon", hour=7, minute=30),
    },
    "social-analytics": {
        "task": "backend.domains.social.workers.analytics.collect_social_analytics",
        "schedule": crontab(hour="*/6", minute=0),
    },
    "hubspot-contact-sync": {
        "task": "backend.workers.hubspot_sync_contacts.sync_contacts",
        "schedule": crontab(minute=f"*/{settings.HUBSPOT_CONTACT_SYNC_MINUTES}"),
    },
    "hubspot-deal-sync": {
        "task": "backend.workers.hubspot_sync_deals.sync_deals",
        "schedule": crontab(minute=f"*/{settings.HUBSPOT_DEAL_SYNC_MINUTES}"),
    },
    "hubspot-company-sync": {
        "task": "backend.workers.hubspot_sync_deals.sync_companies",
        "schedule": crontab(minute=f"*/{settings.HUBSPOT_COMPANY_SYNC_MINUTES}"),
    },
}
