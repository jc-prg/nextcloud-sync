"""SyncScheduler and startup housekeeping."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.database import SessionLocal
from backend.main import _mark_stale_jobs_failed
from backend.models import JobStatus, SyncJob
from backend.sync.scheduler import SyncScheduler
from backend.tests.factories import make_account, make_rule


@pytest.fixture
async def scheduler():
    s = SyncScheduler()
    s.start()
    yield s
    s.stop()


def rule(rule_id=1, cron="*/5 * * * *", enabled=True):
    return SimpleNamespace(id=rule_id, schedule_cron=cron, enabled=enabled)


async def test_add_replace_and_remove(scheduler):
    scheduler.add_rule(rule())
    first = scheduler.next_run_time(1)
    assert first is not None

    scheduler.add_rule(rule(cron="0 0 1 1 *"))  # replaces, no duplicate-id error
    assert scheduler.next_run_time(1) != first
    assert len(scheduler._scheduler.get_jobs()) == 1

    scheduler.remove_rule(1)
    assert scheduler.next_run_time(1) is None
    scheduler.remove_rule(1)  # removing twice is fine


async def test_disabled_rule_removes_its_job(scheduler):
    scheduler.add_rule(rule())
    scheduler.add_rule(rule(enabled=False))
    assert scheduler.next_run_time(1) is None


async def test_invalid_cron_is_skipped(scheduler):
    scheduler.add_rule(rule(cron="every day"))
    assert scheduler.next_run_time(1) is None


async def test_load_rules_schedules_enabled_rules_only(scheduler):
    a, b = await make_account(label="a"), await make_account(label="b")
    on = await make_rule(a, b, enabled=True)
    off = await make_rule(a, b, enabled=False)

    await scheduler.load_rules()

    assert scheduler.next_run_time(on.id) is not None
    assert scheduler.next_run_time(off.id) is None


async def test_stale_running_jobs_are_marked_failed_on_startup():
    a, b = await make_account(label="a"), await make_account(label="b")
    r = await make_rule(a, b)
    async with SessionLocal() as db:
        db.add_all([SyncJob(sync_rule_id=r.id, status=JobStatus.running), SyncJob(sync_rule_id=r.id, status=JobStatus.success)])
        await db.commit()

    await _mark_stale_jobs_failed()

    async with SessionLocal() as db:
        jobs = list((await db.execute(select(SyncJob).order_by(SyncJob.id))).scalars())
    assert [j.status for j in jobs] == [JobStatus.error, JobStatus.success]
    assert jobs[0].finished_at is not None and jobs[1].finished_at is None
