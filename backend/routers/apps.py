import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import App
from backend.routers.devices import check_accounts_exist
from backend.schemas.apps import AppCreate, AppFolder, AppRead, AppUpdate, normalize_folders

router = APIRouter(prefix="/api/apps", tags=["apps"])


@router.get("", response_model=list[AppRead])
async def list_apps(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> list[App]:
    result = await db.execute(select(App).order_by(App.label))
    return list(result.scalars())


@router.post("", response_model=AppRead, status_code=status.HTTP_201_CREATED)
async def add_app(
    body: AppCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> App:
    app = App(label=body.label, note=_clean(body.note), folders=await _dump_folders(db, body.folders))
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


@router.get("/{app_id}", response_model=AppRead)
async def get_app(
    app_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> App:
    return await _get_or_404(db, app_id)


@router.patch("/{app_id}", response_model=AppRead)
async def update_app(
    app_id: int,
    body: AppUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> App:
    app = await _get_or_404(db, app_id)
    if body.label is not None:
        app.label = body.label
    if "note" in body.model_fields_set:
        app.note = _clean(body.note)
    if body.folders is not None:
        app.folders = await _dump_folders(db, body.folders)
    await db.commit()
    await db.refresh(app)
    return app


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app(
    app_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> None:
    app = await _get_or_404(db, app_id)
    await db.delete(app)
    await db.commit()


def _clean(text: str | None) -> str | None:
    text = (text or "").strip()
    return text or None


async def _dump_folders(db: AsyncSession, folders: list[AppFolder]) -> str | None:
    folders = normalize_folders(folders)
    await check_accounts_exist(db, {f.account_id for f in folders})
    return json.dumps([f.model_dump() for f in folders]) if folders else None


async def _get_or_404(db: AsyncSession, app_id: int) -> App:
    app = await db.get(App, app_id)
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App not found")
    return app
