from datetime import datetime

from pydantic import BaseModel

from backend.models import JobStatus, LogLevel


class SyncJobRead(BaseModel):
    id: int
    sync_rule_id: int
    started_at: datetime
    finished_at: datetime | None
    status: JobStatus
    files_added: int
    files_updated: int
    files_deleted: int
    bytes_transferred: int

    model_config = {"from_attributes": True}


class SyncLogRead(BaseModel):
    id: int
    sync_job_id: int
    timestamp: datetime
    level: LogLevel
    message: str
    path: str | None

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    items: list[SyncJobRead]
    total: int


class LogListResponse(BaseModel):
    items: list[SyncLogRead]
    total: int
