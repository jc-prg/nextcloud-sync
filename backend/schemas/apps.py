import json
from datetime import datetime

from pydantic import BaseModel, field_validator

from backend.schemas.devices import _norm


class AppFolder(BaseModel):
    account_id: int
    account_path: str = "/"

    @field_validator("account_path")
    @classmethod
    def normalize(cls, v: str) -> str:
        return _norm(v)


def normalize_folders(folders: list[AppFolder]) -> list[AppFolder]:
    """Drop duplicates, keeping the given order."""
    seen = {}
    for f in folders:
        seen.setdefault((f.account_id, f.account_path), f)
    return list(seen.values())


class AppCreate(BaseModel):
    label: str
    note: str | None = None
    folders: list[AppFolder] = []


class AppUpdate(BaseModel):
    label: str | None = None
    note: str | None = None
    folders: list[AppFolder] | None = None


class AppRead(BaseModel):
    id: int
    label: str
    note: str | None
    folders: list[AppFolder]
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("folders", mode="before")
    @classmethod
    def deserialize_json_list(cls, v):
        if isinstance(v, str) or v is None:
            return json.loads(v) if v else []
        return v
