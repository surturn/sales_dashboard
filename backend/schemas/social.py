from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrendDiscoveryRequest(BaseModel):
    topic: str
    platforms: list[str] | None = None
    limit: int = 12


class SocialPostCreateRequest(BaseModel):
    draft_id: str | None = None
    trend_id: int | None = None
    platform: str | None = None


class SocialPublishRequest(BaseModel):
    schedule_for: datetime | None = None


class SocialTrendRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    platform: str
    keyword: str
    topic: str | None = None
    summary: str | None = None
    score: float
    status: str
    source: str | None = None
    title: str | None = None
    caption: str | None = None
    content: str | None = None
    created_at: datetime


class SocialDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    platform: str
    keyword: str
    topic: str | None = None
    summary: str | None = None
    score: float
    status: str
    source: str | None = None
    title: str | None = None
    caption: str | None = None
    content: str | None = None
    created_at: datetime


class SocialPostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trend_id: int | None = None
    platform: str
    title: str | None = None
    caption: str | None = None
    content: str | None = None
    approval_status: str
    publish_status: str
    scheduled_for: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
