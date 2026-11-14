import json
from typing import Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import Setting

router = APIRouter(prefix="/api/settings", tags=["settings"])

KeyPath = Path(pattern=r"^[a-z0-9_]{1,64}$")


class SettingValue(BaseModel):
    value: Any = None


@router.get("/{key}", response_model=SettingValue)
async def get_setting(
    key: str = KeyPath,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> SettingValue:
    setting = await db.get(Setting, key)
    return SettingValue(value=json.loads(setting.value) if setting else None)


@router.put("/{key}", response_model=SettingValue)
async def put_setting(
    body: SettingValue,
    key: str = KeyPath,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> SettingValue:
    setting = await db.get(Setting, key)
    if setting is None:
        db.add(Setting(key=key, value=json.dumps(body.value)))
    else:
        setting.value = json.dumps(body.value)
    await db.commit()
    return body
