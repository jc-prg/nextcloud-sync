"""/api/jobs, including aborting a running sync."""

import asyncio
from datetime import datetime, timedelta

import pytest

from backend.database import SessionLocal
from backend.models import JobStatus, LogLevel, SyncJob, SyncLog
from backend.sync.engine import run_sync, running_job_ids
from backend.tests.factories import last_job, make_account, make_rule

T0 = datetime(2026, 1, 1)


@pytest.fixture
async def rules():
    a, b = await make_account(label="a"), await make_account(label="b")
    return await make_rule(a, b, label="r1"), await make_rule(a, b, label="r2")


async def add_job(rule_id: int, minutes: int, status: JobStatus = JobStatus.success, logs: int = 0) -> int:
    async with SessionLocal() as db:
        job = SyncJob(sync_rule_id=rule_id, status=status, started_at=T0 + timedelta(minutes=minutes))
        db.add(job)
        await db.flush()
        for i in range(logs):
            db.add(SyncLog(sync_job_id=job.id, level=LogLevel.info, message=f"log {i}", timestamp=T0 + timedelta(seconds=i)))
        await db.commit()
        return job.id


async def test_list_newest_first_with_filter_and_pagination(api, rules):
    r1, r2 = rules
    ids = [await add_job(r1.id, 1), await add_job(r2.id, 2), await add_job(r1.id, 3)]

    data = (await api.get("/api/jobs")).json()
    assert data["total"] == 3 and [j["id"] for j in data["items"]] == ids[::-1]

    data = (await api.get("/api/jobs", params={"rule_id": r1.id})).json()
    assert data["total"] == 2 and [j["id"] for j in data["items"]] == [ids[2], ids[0]]

    data = (await api.get("/api/jobs", params={"limit": 1, "offset": 1})).json()
    assert data["total"] == 3 and [j["id"] for j in data["items"]] == [ids[1]]

    assert (await api.get("/api/jobs", params={"limit": 201})).status_code == 422


async def test_get_job_and_logs(api, rules):
    job_id = await add_job(rules[0].id, 1, logs=5)

    job = (await api.get(f"/api/jobs/{job_id}")).json()
    assert job["status"] == "success" and job["sync_rule_id"] == rules[0].id

    logs = (await api.get(f"/api/jobs/{job_id}/logs", params={"limit": 2, "offset": 1})).json()
    assert logs["total"] == 5 and [entry["message"] for entry in logs["items"]] == ["log 1", "log 2"]

    assert (await api.get("/api/jobs/99")).status_code == 404


async def test_abort_requires_a_running_job(api, rules):
    finished = await add_job(rules[0].id, 1)
    stale = await add_job(rules[0].id, 2, status=JobStatus.running)  # running in DB, but no task

    assert (await api.post(f"/api/jobs/{finished}/abort")).status_code == 409
    assert (await api.post(f"/api/jobs/{stale}/abort")).status_code == 409
    assert (await api.post("/api/jobs/99/abort")).status_code == 404


async def test_abort_cancels_a_running_sync(api, dav):
    src, dst = dav("src"), dav("dst")
    src.mkdir("/sync")
    dst.mkdir("/sync")
    src.gate = asyncio.Event()  # listing the source blocks until the test is done
    rule = await make_rule(await make_account(src), await make_account(dst))

    task = asyncio.create_task(run_sync(rule.id))
    for _ in range(100):
        if running_job_ids():
            break
        await asyncio.sleep(0.01)
    job_id = running_job_ids()[0]

    resp = await api.post(f"/api/jobs/{job_id}/abort")
    await asyncio.wait_for(task, timeout=5)

    assert resp.status_code == 200
    job, logs = await last_job(rule.id)
    assert job.status == JobStatus.aborted and job.finished_at is not None
    assert logs[-1].message == "Job aborted by user"
    assert running_job_ids() == []
