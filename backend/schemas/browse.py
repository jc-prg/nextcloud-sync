from datetime import datetime

from pydantic import BaseModel


class BrowseEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    mtime: datetime | None
    etag: str | None


class BrowseResponse(BaseModel):
    path: str
    entries: list[BrowseEntry]
