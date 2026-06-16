from datetime import datetime

from pydantic import BaseModel

from backend.models import SyncDirection


class SyncRuleCreate(BaseModel):
    label: str
    enabled: bool = True
    source_account_id: int
    source_path: str
    dest_account_id: int
    dest_path: str
    direction: SyncDirection = SyncDirection.one_way
    schedule_cron: str
    delete_orphans: bool = False


class SyncRuleUpdate(BaseModel):
    label: str | None = None
    enabled: bool | None = None
    source_account_id: int | None = None
    source_path: str | None = None
    dest_account_id: int | None = None
    dest_path: str | None = None
    direction: SyncDirection | None = None
    schedule_cron: str | None = None
    delete_orphans: bool | None = None


class SyncRuleRead(BaseModel):
    id: int
    label: str
    enabled: bool
    source_account_id: int
    source_path: str
    dest_account_id: int
    dest_path: str
    direction: SyncDirection
    schedule_cron: str
    delete_orphans: bool
    last_run_at: datetime | None
    next_run_at: datetime | None

    model_config = {"from_attributes": True}
