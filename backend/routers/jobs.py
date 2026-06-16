from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import get_current_user
from backend.database import get_db
from backend.models import SyncJob, SyncLog
from backend.schemas.jobs import JobListResponse, LogListResponse, SyncJobRead, SyncLogRead

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse)
async def list_jobs(
    rule_id: int | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> JobListResponse:
    q = select(SyncJob).order_by(SyncJob.started_at.desc())
    count_q = select(func.count()).select_from(SyncJob)
    if rule_id is not None:
        q = q.where(SyncJob.sync_rule_id == rule_id)
        count_q = count_q.where(SyncJob.sync_rule_id == rule_id)

    total = (await db.execute(count_q)).scalar_one()
    jobs = list((await db.execute(q.offset(offset).limit(limit))).scalars())
    return JobListResponse(items=jobs, total=total)


@router.get("/{job_id}", response_model=SyncJobRead)
async def get_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> SyncJob:
    result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("/{job_id}/abort", status_code=status.HTTP_200_OK)
async def abort_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> dict:
    from backend.sync.engine import abort_job as _abort

    result = await db.execute(select(SyncJob).where(SyncJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status != "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is not running")
    if not _abort(job_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is not running")
    return {"detail": "Abort requested"}


@router.get("/{job_id}/logs", response_model=LogListResponse)
async def get_job_logs(
    job_id: int,
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> LogListResponse:
    q = select(SyncLog).where(SyncLog.sync_job_id == job_id).order_by(SyncLog.timestamp)
    count_q = select(func.count()).select_from(SyncLog).where(SyncLog.sync_job_id == job_id)
    total = (await db.execute(count_q)).scalar_one()
    logs = list((await db.execute(q.offset(offset).limit(limit))).scalars())
    return LogListResponse(items=logs, total=total)
