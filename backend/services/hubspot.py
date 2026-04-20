from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.app.config import get_settings
from backend.services import ExternalServiceError, ServiceConfigurationError


class HubSpotClient:
    def __init__(
        self,
        access_token: str | None = None,
        base_url: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        settings = get_settings()
        self.access_token = access_token or settings.HUBSPOT_ACCESS_TOKEN
        self.base_url = (base_url or settings.HUBSPOT_BASE_URL).rstrip("/")
        self.client = http_client or httpx.Client(timeout=30)

    def _headers(self) -> dict[str, str]:
        if not self.access_token:
            raise ServiceConfigurationError("HUBSPOT_ACCESS_TOKEN is not configured")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "BizardLeads/1.0",
        }

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.client.request(
            method=method,
            url=f"{self.base_url}{path}",
            headers=self._headers(),
            params=params,
            json=json,
        )
        if response.is_error:
            raise ExternalServiceError(f"HubSpot request failed for {path}: {response.text}")
        return response.json()

    @staticmethod
    def _updated_after_value(updated_after: datetime | None) -> str | None:
        if updated_after is None:
            return None
        normalized = updated_after.astimezone(UTC) if updated_after.tzinfo else updated_after.replace(tzinfo=UTC)
        return normalized.isoformat().replace("+00:00", "Z")

    def list_contacts(self, *, limit: int = 100, after: str | None = None, updated_after: datetime | None = None) -> dict[str, Any]:
        params = {
            "limit": limit,
            "after": after,
            "updatedAfter": self._updated_after_value(updated_after),
            "properties": ",".join(
                [
                    "firstname",
                    "lastname",
                    "email",
                    "phone",
                    "company",
                    "website",
                    "jobtitle",
                    "lifecyclestage",
                    "createdate",
                    "hs_lastmodifieddate",
                    "linkedinbio",
                ]
            ),
        }
        return self._request("GET", "/crm/v3/objects/contacts", params={key: value for key, value in params.items() if value is not None})

    def list_deals(self, *, limit: int = 100, after: str | None = None, updated_after: datetime | None = None) -> dict[str, Any]:
        params = {
            "limit": limit,
            "after": after,
            "updatedAfter": self._updated_after_value(updated_after),
            "properties": ",".join(
                [
                    "dealname",
                    "amount",
                    "dealstage",
                    "closedate",
                    "createdate",
                    "hs_lastmodifieddate",
                    "pipeline",
                ]
            ),
        }
        return self._request("GET", "/crm/v3/objects/deals", params={key: value for key, value in params.items() if value is not None})

    def list_companies(self, *, limit: int = 100, after: str | None = None, updated_after: datetime | None = None) -> dict[str, Any]:
        params = {
            "limit": limit,
            "after": after,
            "updatedAfter": self._updated_after_value(updated_after),
            "properties": ",".join(
                [
                    "name",
                    "domain",
                    "phone",
                    "city",
                    "createdate",
                    "hs_lastmodifieddate",
                ]
            ),
        }
        return self._request("GET", "/crm/v3/objects/companies", params={key: value for key, value in params.items() if value is not None})

    def batch_read_contacts(self, contact_ids: Iterable[str]) -> dict[str, Any]:
        ids = [str(contact_id) for contact_id in contact_ids if contact_id]
        if not ids:
            return {"results": []}
        return self._request(
            "POST",
            "/crm/v3/objects/contacts/batch/read",
            json={
                "properties": [
                    "firstname",
                    "lastname",
                    "email",
                    "phone",
                    "company",
                    "website",
                    "jobtitle",
                    "lifecyclestage",
                    "createdate",
                    "hs_lastmodifieddate",
                    "linkedinbio",
                ],
                "inputs": [{"id": contact_id} for contact_id in ids],
            },
        )

    def batch_read_deals(self, deal_ids: Iterable[str]) -> dict[str, Any]:
        ids = [str(deal_id) for deal_id in deal_ids if deal_id]
        if not ids:
            return {"results": []}
        return self._request(
            "POST",
            "/crm/v3/objects/deals/batch/read",
            json={
                "properties": [
                    "dealname",
                    "amount",
                    "dealstage",
                    "closedate",
                    "createdate",
                    "hs_lastmodifieddate",
                    "pipeline",
                ],
                "inputs": [{"id": deal_id} for deal_id in ids],
            },
        )

    def get_contacts(self, limit: int = 100) -> dict[str, Any]:
        return self.list_contacts(limit=limit)

    def get_deals(self, limit: int = 100) -> dict[str, Any]:
        return self.list_deals(limit=limit)

    def create_contact(self, properties: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/crm/v3/objects/contacts", json={"properties": properties})

    def update_contact(self, contact_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/crm/v3/objects/contacts/{contact_id}", json={"properties": properties})

    def update_contact_by_email(self, email: str, properties: dict[str, Any]) -> dict[str, Any]:
        response = self.client.patch(
            f"{self.base_url}/crm/v3/objects/contacts/{email}",
            headers=self._headers(),
            params={"idProperty": "email"},
            json={"properties": properties},
        )
        if response.status_code == 404:
            return {"not_found": True}
        if response.is_error:
            raise ExternalServiceError(f"HubSpot contact update by email failed: {response.text}")
        return response.json()

    def batch_upsert_contacts(self, contacts: list[dict[str, Any]]) -> dict[str, Any]:
        inputs = []
        for properties in contacts:
            email = properties.get("email")
            if not email:
                continue
            inputs.append(
                {
                    "id": email,
                    "idProperty": "email",
                    "properties": properties,
                }
            )
        if not inputs:
            return {"results": [], "skipped": True}

        return self._request("POST", "/crm/v3/objects/contacts/batch/upsert", json={"inputs": inputs})

    def create_or_update_contact(self, properties: dict[str, Any]) -> dict[str, Any]:
        email = properties.get("email")
        if not email:
            return {"skipped": True, "reason": "missing_email"}
        updated = self.update_contact_by_email(email, properties)
        if updated.get("not_found"):
            return self.create_contact(properties)
        return updated
