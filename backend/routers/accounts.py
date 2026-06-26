from fastapi import APIRouter, Depends, HTTPException, status
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
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> Account:
    account = Account(
        label=body.label,
        webdav_url=body.webdav_url.rstrip("/"),
        username=body.username,
        password_enc=encrypt(body.password),
        storage_limit_bytes=body.storage_limit_bytes,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
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
    await db.commit()
    await db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> None:
    account = await _get_or_404(db, account_id)
    await db.delete(account)
    await db.commit()


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


async def _get_or_404(db: AsyncSession, account_id: int) -> Account:
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account
