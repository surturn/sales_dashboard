"""Approval endpoints for the outreach human-in-the-loop gate."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.dependencies import get_current_user
from backend.app.database import get_db
from backend.models.outreach_approval_queue import OutreachApprovalQueue
from backend.models.user import User

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/pending")
async def list_pending(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the current user's pending outreach drafts."""
    rows = db.scalars(
        select(OutreachApprovalQueue)
        .where(OutreachApprovalQueue.user_id == user.id, OutreachApprovalQueue.status == "pending")
        .order_by(OutreachApprovalQueue.created_at.desc())
    ).all()
    return {
        "pending": [
            {
                "id": row.id,
                "lead_id": row.lead_id,
                "lead_email": row.lead_email,
                "draft": row.draft,
                "thread_id": row.thread_id,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


def _get_queue_row(db: Session, *, draft_id: str, user_id: int) -> OutreachApprovalQueue:
    row = db.scalar(
        select(OutreachApprovalQueue).where(
            OutreachApprovalQueue.id == draft_id,
            OutreachApprovalQueue.user_id == user_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval draft not found")
    if not row.thread_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval draft is missing thread information")
    return row


@router.post("/{draft_id}/approve")
async def approve_draft(
    draft_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a draft approved, inject the decision into the graph, and resume it."""
    row = _get_queue_row(db, draft_id=draft_id, user_id=user.id)
    final_draft = body.get("final_draft") or row.draft
    row.status = "approved"
    row.final_draft = final_draft
    row.decided_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()

    from backend.app.agents.outreach import build_outreach_graph

    graph = await build_outreach_graph()
    config = {"configurable": {"thread_id": row.thread_id}}
    updated_config = await graph.aupdate_state(
        config,
        {"approved": True, "final_draft": final_draft},
        as_node="approval_gate",
    )
    await graph.ainvoke(None, config=updated_config)
    return {"status": "resumed", "draft_id": draft_id, "final_draft": final_draft}


@router.post("/{draft_id}/reject")
async def reject_draft(
    draft_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resume the paused graph with an explicit rejection."""
    row = _get_queue_row(db, draft_id=draft_id, user_id=user.id)
    row.status = "rejected"
    row.decided_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()

    from backend.app.agents.outreach import build_outreach_graph

    graph = await build_outreach_graph()
    config = {"configurable": {"thread_id": row.thread_id}}
    updated_config = await graph.aupdate_state(
        config,
        {"approved": False, "final_draft": row.draft},
        as_node="approval_gate",
    )
    await graph.ainvoke(None, config=updated_config)
    return {"status": "rejected", "draft_id": draft_id}
