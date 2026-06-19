import json
from datetime import datetime

from pydantic import BaseModel, field_validator

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
    exclude_patterns: list[str] = []
    exclude_subfolders: list[str] = []
    min_file_size: int | None = None  # bytes
    max_file_size: int | None = None  # bytes


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
    exclude_patterns: list[str] | None = None
    exclude_subfolders: list[str] | None = None
    min_file_size: int | None = None
    max_file_size: int | None = None


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
    exclude_patterns: list[str] = []
    exclude_subfolders: list[str] = []
    min_file_size: int | None
    max_file_size: int | None
    last_run_at: datetime | None
    next_run_at: datetime | None

    @field_validator("exclude_patterns", "exclude_subfolders", mode="before")
    @classmethod
    def deserialize_json_list(cls, v):
        if isinstance(v, str):
            return json.loads(v) if v else []
        return v or []

    model_config = {"from_attributes": True}
