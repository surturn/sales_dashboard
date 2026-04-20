from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class OutreachApprovalQueue(Base):
    __tablename__ = "outreach_approval_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), index=True, nullable=True)
    lead_email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    draft: Mapped[str] = mapped_column(Text, nullable=False)
    final_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

