import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import Account, Device
from backend.schemas.devices import DeviceCreate, DeviceFolder, DeviceRead, DeviceUpdate, normalize_folders

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("", response_model=list[DeviceRead])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> list[Device]:
    result = await db.execute(select(Device).order_by(Device.label))
    return list(result.scalars())


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
async def create_device(
    body: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> Device:
    device = Device(label=body.label, folders=await _dump_folders(db, body.folders))
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> Device:
    return await _get_or_404(db, device_id)


@router.patch("/{device_id}", response_model=DeviceRead)
async def update_device(
    device_id: int,
    body: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> Device:
    device = await _get_or_404(db, device_id)
    if body.label is not None:
        device.label = body.label
    if body.folders is not None:
        device.folders = await _dump_folders(db, body.folders)
    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> None:
    device = await _get_or_404(db, device_id)
    await db.delete(device)
    await db.commit()


async def _dump_folders(db: AsyncSession, folders: list[DeviceFolder]) -> str | None:
    folders = normalize_folders(folders)
    linked = {f.account_id for f in folders if f.account_id is not None}
    if linked:
        known = set((await db.execute(select(Account.id).where(Account.id.in_(linked)))).scalars())
        if linked - known:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown account id(s): {sorted(linked - known)}",
            )
    return json.dumps([f.model_dump() for f in folders]) if folders else None


async def _get_or_404(db: AsyncSession, device_id: int) -> Device:
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device
