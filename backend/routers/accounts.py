from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.crypto import decrypt, encrypt
from backend.database import get_db
from backend.models import Account
from backend.schemas.accounts import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    ConnectionTestResult,
)
from backend.sync.nccron import run_cron
from backend.sync.webdav import WebDAVClient

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountRead])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> list[Account]:
    result = await db.execute(select(Account).order_by(Account.label))
    return list(result.scalars())


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
async def create_account(
    body: AccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> Account:
    account = Account(
        label=body.label,
        webdav_url=body.webdav_url.rstrip("/"),
        username=body.username,
        password_enc=encrypt(body.password),
        storage_limit_bytes=body.storage_limit_bytes,
        cron_enabled=body.cron_enabled,
        cron_interval_minutes=body.cron_interval_minutes,
        cron_url=_clean_url(body.cron_url),
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    request.app.state.scheduler.add_account_cron(account)
    return account


@router.get("/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> Account:
    return await _get_or_404(db, account_id)


@router.patch("/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: int,
    body: AccountUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> Account:
    account = await _get_or_404(db, account_id)
    if body.label is not None:
        account.label = body.label
    if body.webdav_url is not None:
        account.webdav_url = body.webdav_url.rstrip("/")
    if body.username is not None:
        account.username = body.username
    if body.password is not None:
        account.password_enc = encrypt(body.password)
    if "storage_limit_bytes" in body.model_fields_set:
        account.storage_limit_bytes = body.storage_limit_bytes
    if body.cron_enabled is not None:
        account.cron_enabled = body.cron_enabled
    if body.cron_interval_minutes is not None:
        account.cron_interval_minutes = body.cron_interval_minutes
    if "cron_url" in body.model_fields_set:
        account.cron_url = _clean_url(body.cron_url)
    await db.commit()
    await db.refresh(account)
    request.app.state.scheduler.add_account_cron(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> None:
    account = await _get_or_404(db, account_id)
    await db.delete(account)
    await db.commit()
    request.app.state.scheduler.remove_account_cron(account_id)


@router.get("/{account_id}/quota")
async def get_quota(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    account = await _get_or_404(db, account_id)
    try:
        password = decrypt(account.password_enc)
        async with WebDAVClient(account.webdav_url, account.username, password) as client:
            used, available = await client.get_quota()
        return {"used": used, "available": available}
    except Exception as exc:
        return {"used": None, "available": None, "error": str(exc)}


@router.post("/{account_id}/test", response_model=ConnectionTestResult)
async def test_connection(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> ConnectionTestResult:
    account = await _get_or_404(db, account_id)
    try:
        password = decrypt(account.password_enc)
        async with WebDAVClient(account.webdav_url, account.username, password) as client:
            ok = await client.test_connection()
        return ConnectionTestResult(ok=ok)
    except Exception as exc:
        return ConnectionTestResult(ok=False, error=str(exc))


@router.post("/{account_id}/cron", response_model=AccountRead)
async def run_cron_now(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> Account:
    """Call the account's cron.php right away (also when the periodic call is disabled)."""
    await _get_or_404(db, account_id)
    return await run_cron(account_id)


def _clean_url(url: str | None) -> str | None:
    url = (url or "").strip()
    return url or None


async def _get_or_404(db: AsyncSession, account_id: int) -> Account:
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account
