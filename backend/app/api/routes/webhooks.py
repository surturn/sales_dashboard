import hashlib
import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status

from backend.app.config import get_settings
from backend.app.core.rate_limit import limiter
from backend.domains.leads.services.outreach_service import process_hubspot_webhook
from backend.workers.support import process_chatwoot_webhook


router = APIRouter(prefix="/webhooks", tags=["webhooks"])
settings = get_settings()


def verify_hubspot_signature(signature: str, payload: bytes, secret: str) -> bool:
    computed = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, computed)


@router.post("/hubspot", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.RATE_LIMIT_WEBHOOKS)
async def hubspot_webhook(request: Request, x_hubspot_signature: str | None = Header(default=None)) -> dict:
    body = await request.body()
    secret = settings.HUBSPOT_WEBHOOK_SECRET or settings.HUBSPOT_API_KEY
    if not x_hubspot_signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing HubSpot signature")
    if not verify_hubspot_signature(x_hubspot_signature, body, secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid HubSpot signature")
    process_hubspot_webhook(body)
    return {"status": "accepted"}


@router.post("/chatwoot", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.RATE_LIMIT_WEBHOOKS)
async def chatwoot_webhook(request: Request) -> dict:
    process_chatwoot_webhook(await request.json())
    return {"status": "accepted"}
