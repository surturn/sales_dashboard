from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_name: str
    trigger_source: str
    status: str
    records_processed: int = 0
    records_created: int = 0
    execution_time: float | None = None
    payload: str | None = None
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
