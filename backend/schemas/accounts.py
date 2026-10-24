from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class AccountCreate(BaseModel):
    label: str
    webdav_url: str
    username: str
    password: str
    storage_limit_bytes: int | None = None
    cron_enabled: bool = False
    cron_interval_minutes: int = Field(5, ge=1, le=1440)
    cron_url: str | None = None


class AccountUpdate(BaseModel):
    label: str | None = None
    webdav_url: str | None = None
    username: str | None = None
    password: str | None = None
    storage_limit_bytes: int | None = None
    cron_enabled: bool | None = None
    cron_interval_minutes: int | None = Field(None, ge=1, le=1440)
    cron_url: str | None = None


class AccountRead(BaseModel):
    id: int
    label: str
    webdav_url: str
    username: str
    storage_limit_bytes: int | None
    cron_enabled: bool
    cron_interval_minutes: int
    cron_url: str | None
    cron_effective_url: str | None = None  # cron_url, or the one derived from webdav_url
    cron_last_run_at: datetime | None
    cron_last_ok: bool | None
    cron_last_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectionTestResult(BaseModel):
    ok: bool
    error: str | None = None
