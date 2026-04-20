import json
import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from backend.app.config import get_settings
from backend.app.core.rate_limit import limiter
from backend.app.core.security import has_hubspot_object_id, has_valid_shared_secret, is_supported_hubspot_webhook_event
from backend.workers.support import process_chatwoot_webhook
from backend.workers.webhook_dispatcher import dispatch_hubspot_webhook_task
from backend.app.agents.entrypoints import try_handle_hubspot_events, try_handle_chatwoot_event


router = APIRouter(prefix="/webhooks", tags=["webhooks"])
settings = get_settings()
logger = logging.getLogger(__name__)

class HubSpotWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    subscriptionType: str | None = None
    eventType: str | None = None
    objectId: int | str | None = None
    object_id: int | str | None = None
    id: int | str | None = None


class HubSpotWebhookEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    events: list[HubSpotWebhookEvent]


hubspot_webhook_payload_adapter = TypeAdapter(list[HubSpotWebhookEvent] | HubSpotWebhookEnvelope | HubSpotWebhookEvent)


def _normalize_hubspot_events(payload: object) -> list[dict]:
    try:
        validated = hubspot_webhook_payload_adapter.validate_python(payload)
    except ValidationError as exc:
        logger.warning("Rejected HubSpot webhook with invalid payload structure: %s", exc.errors())
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid HubSpot webhook payload") from exc

    if isinstance(validated, list):
        events = validated
    elif isinstance(validated, HubSpotWebhookEnvelope):
        events = validated.events
    else:
        events = [validated]

    dispatchable_events = []
    for event in events:
        event_data = event.model_dump(exclude_none=True)
        if is_supported_hubspot_webhook_event(event_data) and has_hubspot_object_id(event_data):
            dispatchable_events.append(event_data)

    if not dispatchable_events:
        logger.warning("Rejected HubSpot webhook without dispatchable events: %s", payload)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid HubSpot webhook payload")

    return dispatchable_events


@router.post("/hubspot", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.RATE_LIMIT_WEBHOOKS)
async def hubspot_webhook(request: Request) -> dict:
    expected_secret = settings.HUBSPOT_CLIENT_SECRET
    provided_secret = request.headers.get(settings.HUBSPOT_WEBHOOK_SHARED_HEADER_NAME)
    if not expected_secret:
        logger.error("Rejected HubSpot webhook because the shared secret is not configured")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="HubSpot webhook shared secret not configured")
    if not has_valid_shared_secret(expected_secret, provided_secret):
        logger.warning("Rejected HubSpot webhook with invalid shared header")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook credentials")

    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        logger.warning("Rejected HubSpot webhook with invalid JSON: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    dispatchable_events = _normalize_hubspot_events(payload)
    # Try agent handler first. If it returns False, fall back to existing task.
    try:
        handled = try_handle_hubspot_events(dispatchable_events)
    except Exception:
        handled = False

    if not handled:
        dispatch_hubspot_webhook_task.delay(json.dumps(dispatchable_events))
        return {"status": "accepted", "queued": True, "events": len(dispatchable_events)}
    return {"status": "accepted", "queued": False, "events": len(dispatchable_events), "agent_handled": True}


@router.post("/chatwoot", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.RATE_LIMIT_WEBHOOKS)
async def chatwoot_webhook(request: Request) -> dict:
    payload = await request.json()
    try:
        handled = try_handle_chatwoot_event(payload)
    except Exception:
        handled = False

    if not handled:
        process_chatwoot_webhook(payload)
        return {"status": "accepted", "queued": True}
    return {"status": "accepted", "queued": False, "agent_handled": True}
