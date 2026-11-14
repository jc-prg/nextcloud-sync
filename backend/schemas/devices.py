import json
from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator


def _norm(path: str) -> str:
    return "/" + "/".join(seg for seg in path.split("/") if seg)


class DeviceFolder(BaseModel):
    path: str
    account_id: int | None = None  # linked account, synced by the Nextcloud client
    account_path: str | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.path = _norm(self.path)
        if self.path == "/":
            raise ValueError("folder path must not be empty")
        if self.account_id is None:
            self.account_path = None
        else:
            self.account_path = _norm(self.account_path or "/")
        return self


def normalize_folders(folders: list[DeviceFolder]) -> list[DeviceFolder]:
    """Drop duplicate paths (last wins), add missing ancestors and sort as a tree."""
    by_path = {f.path: f for f in folders}
    for path in list(by_path):
        parts = path.split("/")[1:-1]
        for i in range(1, len(parts) + 1):
            by_path.setdefault("/" + "/".join(parts[:i]), DeviceFolder(path="/" + "/".join(parts[:i])))
    return [by_path[p] for p in sorted(by_path, key=lambda p: p.lower().split("/"))]


class DeviceCreate(BaseModel):
    label: str
    folders: list[DeviceFolder] = []


class DeviceUpdate(BaseModel):
    label: str | None = None
    folders: list[DeviceFolder] | None = None


class DeviceRead(BaseModel):
    id: int
    label: str
    folders: list[DeviceFolder]
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("folders", mode="before")
    @classmethod
    def deserialize_json_list(cls, v):
        if isinstance(v, str) or v is None:
            return json.loads(v) if v else []
        return v
