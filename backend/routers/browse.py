from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.crypto import decrypt
from backend.database import get_db
from backend.models import Account
from backend.schemas.browse import BrowseEntry, BrowseResponse
from backend.sync.webdav import WebDAVClient

router = APIRouter(prefix="/api/browse", tags=["browse"])


@router.get("", response_model=BrowseResponse)
async def browse(
    account_id: int = Query(...),
    path: str = Query(default="/"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> BrowseResponse:
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    try:
        password = decrypt(account.password_enc)
        async with WebDAVClient(account.webdav_url, account.username, password) as client:
            raw_entries = await client.propfind(path, depth=1)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"WebDAV error: {exc}",
        )

    # Exclude the requested path itself (server returns it as first entry)
    norm = path.rstrip("/") + "/"
    entries = [
        BrowseEntry(
            name=e.name,
            path=e.rel_path,
            is_dir=e.is_dir,
            size=e.size,
            mtime=e.mtime,
            etag=e.etag,
        )
        for e in raw_entries
        if e.rel_path.rstrip("/") != path.rstrip("/")
    ]

    return BrowseResponse(path=path, entries=entries)
