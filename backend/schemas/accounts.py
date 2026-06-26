from datetime import datetime

from pydantic import BaseModel, HttpUrl


class AccountCreate(BaseModel):
    label: str
    webdav_url: str
    username: str
    password: str
    storage_limit_bytes: int | None = None


class AccountUpdate(BaseModel):
    label: str | None = None
    webdav_url: str | None = None
    username: str | None = None
    password: str | None = None
    storage_limit_bytes: int | None = None


class AccountRead(BaseModel):
    id: int
    label: str
    webdav_url: str
    username: str
    storage_limit_bytes: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectionTestResult(BaseModel):
    ok: bool
    error: str | None = None
