from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class LeadCreate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    company_domain: str | None = None
    linkedin_url: str | None = None
    title: str | None = None
    industry: str | None = None
    source: str = "manual"
    status: str = "new"


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    company_domain: str | None = None
    linkedin_url: str | None = None
    title: str | None = None
    industry: str | None = None
    source: str
    status: str
    created_at: datetime
