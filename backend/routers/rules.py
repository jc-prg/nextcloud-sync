import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import SyncRule
from backend.schemas.rules import SyncRuleCreate, SyncRuleRead, SyncRuleUpdate

router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.get("", response_model=list[SyncRuleRead])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> list[SyncRule]:
    result = await db.execute(select(SyncRule).order_by(SyncRule.label))
    return list(result.scalars())


@router.post("", response_model=SyncRuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: SyncRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> SyncRule:
    data = body.model_dump()
    data["exclude_patterns"] = json.dumps(data["exclude_patterns"]) if data.get("exclude_patterns") else None
    data["exclude_subfolders"] = json.dumps(data["exclude_subfolders"]) if data.get("exclude_subfolders") else None
    data["known_subfolders"] = json.dumps(data["known_subfolders"]) if data.get("known_subfolders") else None
    rule = SyncRule(**data)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    _scheduler(request).add_rule(rule)
    return rule


@router.get("/{rule_id}", response_model=SyncRuleRead)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> SyncRule:
    return await _get_or_404(db, rule_id)


@router.patch("/{rule_id}", response_model=SyncRuleRead)
async def update_rule(
    rule_id: int,
    body: SyncRuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> SyncRule:
    rule = await _get_or_404(db, rule_id)
    for field, value in body.model_dump(exclude_none=True).items():
        if field in ("exclude_patterns", "exclude_subfolders", "known_subfolders"):
            value = json.dumps(value) if value else None
        setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    _scheduler(request).add_rule(rule)  # replace_existing=True handles reschedule
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> None:
    rule = await _get_or_404(db, rule_id)
    _scheduler(request).remove_rule(rule.id)
    await db.delete(rule)
    await db.commit()


@router.post("/{rule_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_run(
    rule_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    rule = await _get_or_404(db, rule_id)
    _scheduler(request).run_now(rule.id)
    return {"detail": "Sync job queued"}


async def _get_or_404(db: AsyncSession, rule_id: int) -> SyncRule:
    result = await db.execute(select(SyncRule).where(SyncRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


def _scheduler(request: Request):
    return request.app.state.scheduler
