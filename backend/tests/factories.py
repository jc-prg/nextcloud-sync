"""Helpers to create database rows and read back sync results."""

from sqlalchemy import select

from backend.crypto import encrypt
from backend.database import SessionLocal
from backend.models import Account, SyncDirection, SyncJob, SyncLog, SyncRule
from backend.sync.engine import run_sync
from backend.tests.fakedav import FakeDav


async def make_account(server: FakeDav | None = None, label: str = "acc", password: str = "secret") -> Account:
    async with SessionLocal() as db:
        account = Account(
            label=label,
            webdav_url=server.base_url if server else "http://nowhere.test/dav",
            username="user",
            password_enc=encrypt(password),
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account


async def make_rule(src: Account, dst: Account, **fields) -> SyncRule:
    values = dict(
        label="rule",
        source_account_id=src.id,
        source_path="/sync",
        dest_account_id=dst.id,
        dest_path="/sync",
        schedule_cron="0 * * * *",
        direction=SyncDirection.one_way,
    )
    values.update(fields)
    async with SessionLocal() as db:
        rule = SyncRule(**values)
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        return rule


async def update_rule(rule_id: int, **fields) -> None:
    async with SessionLocal() as db:
        rule = await db.get(SyncRule, rule_id)
        for k, v in fields.items():
            setattr(rule, k, v)
        await db.commit()


async def last_job(rule_id: int) -> tuple[SyncJob, list[SyncLog]]:
    async with SessionLocal() as db:
        job = (
            await db.execute(
                select(SyncJob).where(SyncJob.sync_rule_id == rule_id).order_by(SyncJob.id.desc()).limit(1)
            )
        ).scalar_one()
        logs = list(
            (await db.execute(select(SyncLog).where(SyncLog.sync_job_id == job.id).order_by(SyncLog.id))).scalars()
        )
        return job, logs


async def sync(rule_id: int) -> tuple[SyncJob, list[str]]:
    """Run the rule like the scheduler does and return the job plus its log messages."""
    await run_sync(rule_id)
    job, logs = await last_job(rule_id)
    return job, [log.message for log in logs]
