from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from uuid import uuid4

from backend.app.config import get_settings
from backend.app.core.cache import CacheBackend, build_cache_key


class DraftSessionService:
    def __init__(self, cache: CacheBackend | None = None):
        settings = get_settings()
        self.cache = cache or CacheBackend()
        self.ttl_seconds = settings.SOCIAL_DRAFT_SESSION_TTL_SECONDS

    def build_key(self, user_id: int | None) -> str:
        return build_cache_key("session", "drafts", user_id or "global")

    def list_drafts(self, user_id: int | None) -> list[dict]:
        drafts = self.cache.get(self.build_key(user_id)) or []
        normalized = self._normalize_collection(drafts)
        if normalized:
            self.cache.set(self.build_key(user_id), normalized, ttl=self.ttl_seconds)
        return normalized

    def store_drafts(self, user_id: int | None, drafts: list[dict]) -> list[dict]:
        normalized = self._normalize_collection(drafts)
        self.cache.set(self.build_key(user_id), normalized, ttl=self.ttl_seconds)
        return normalized

    def clear_drafts(self, user_id: int | None) -> None:
        self.cache.delete(self.build_key(user_id))

    def get_draft(self, user_id: int | None, draft_id: str) -> dict | None:
        for draft in self.list_drafts(user_id):
            if draft["id"] == str(draft_id):
                return deepcopy(draft)
        return None

    def pop_draft(self, user_id: int | None, draft_id: str) -> dict | None:
        draft_id = str(draft_id)
        drafts = self.list_drafts(user_id)
        remaining: list[dict] = []
        removed: dict | None = None
        for draft in drafts:
            if draft["id"] == draft_id and removed is None:
                removed = deepcopy(draft)
                continue
            remaining.append(draft)

        if remaining:
            self.store_drafts(user_id, remaining)
        else:
            self.clear_drafts(user_id)
        return removed

    def remove_draft(self, user_id: int | None, draft_id: str) -> bool:
        removed = self.pop_draft(user_id, draft_id)
        return removed is not None

    def seed_draft(self, payload: dict) -> dict:
        draft = deepcopy(payload)
        draft["id"] = str(draft.get("id") or uuid4())
        draft["created_at"] = self._normalize_timestamp(draft.get("created_at")) or datetime.utcnow().isoformat()
        draft["status"] = str(draft.get("status") or "draft")
        draft["score"] = float(draft.get("score") or 0.0)
        return draft

    def _normalize_collection(self, drafts: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for draft in drafts:
            if not isinstance(draft, dict):
                continue
            normalized.append(self.seed_draft(draft))
        return normalized

    @staticmethod
    def _normalize_timestamp(value: object) -> str | None:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str) and value.strip():
            return value
        return None
