"""Periodic cron.php calls for Nextcloud accounts."""

from types import SimpleNamespace

import pytest

from backend.database import SessionLocal
from backend.models import Account
from backend.sync.nccron import run_cron
from backend.sync.scheduler import SyncScheduler
from backend.tests.factories import make_account


def body(**kw):
    values = dict(label="Cloud", webdav_url="http://nc.test/remote.php/dav/files/user", username="user", password="pw")
    values.update(kw)
    return values


def test_cron_url_is_derived_from_nextcloud_webdav_url():
    assert Account(webdav_url="https://c.example/nc/remote.php/dav/files/u").cron_effective_url == "https://c.example/nc/cron.php"
    assert Account(webdav_url="https://dav.example/files").cron_effective_url is None
    assert Account(webdav_url="https://dav.example/files", cron_url="https://x/cron.php").cron_effective_url == "https://x/cron.php"


async def test_run_cron_success(dav):
    server = dav("nc", nextcloud=True)
    account = await make_account(server)

    result = await run_cron(account.id)

    assert server.cron_calls == 1
    assert result.cron_last_ok is True and result.cron_last_error is None and result.cron_last_run_at is not None


async def test_run_cron_reports_system_cron_mode(dav):
    server = dav("nc", nextcloud=True)
    server.cron_response = {"data": {"message": "Backgroundjobs are using system cron!"}, "status": "error"}
    account = await make_account(server)

    result = await run_cron(account.id)

    assert result.cron_last_ok is False and result.cron_last_error == "Backgroundjobs are using system cron!"


async def test_run_cron_http_and_connection_errors(dav):
    server = dav("nc", nextcloud=True)
    server.fail("GET", "/cron.php", 503)
    failing = await make_account(server)
    down = await make_account(label="down")
    async with SessionLocal() as db:
        (await db.get(Account, down.id)).cron_url = "http://down.test/cron.php"
        await db.commit()

    assert (await run_cron(failing.id)).cron_last_error == "HTTP 503"
    assert (await run_cron(down.id)).cron_last_error.startswith("ConnectError")


async def test_run_cron_without_url():
    account = await make_account()  # http://nowhere.test/dav, not a Nextcloud URL
    result = await run_cron(account.id)
    assert result.cron_last_ok is False and "No cron URL" in result.cron_last_error


@pytest.fixture
async def scheduler():
    s = SyncScheduler()
    s.start()
    yield s
    s.stop()


async def test_scheduler_add_replace_and_remove(scheduler):
    scheduler.add_account_cron(SimpleNamespace(id=1, cron_enabled=True, cron_interval_minutes=5))
    first = scheduler.next_cron_time(1)
    assert first is not None

    scheduler.add_account_cron(SimpleNamespace(id=1, cron_enabled=True, cron_interval_minutes=60))
    assert scheduler.next_cron_time(1) > first
    assert len(scheduler._scheduler.get_jobs()) == 1

    scheduler.add_account_cron(SimpleNamespace(id=1, cron_enabled=False, cron_interval_minutes=60))
    assert scheduler.next_cron_time(1) is None
    scheduler.remove_account_cron(1)  # removing twice is fine


async def test_load_accounts_schedules_enabled_only(scheduler):
    on = await make_account(label="on")
    off = await make_account(label="off")
    async with SessionLocal() as db:
        (await db.get(Account, on.id)).cron_enabled = True
        await db.commit()

    await scheduler.load_accounts()

    assert scheduler.next_cron_time(on.id) is not None
    assert scheduler.next_cron_time(off.id) is None


async def test_api_create_update_delete_manage_schedule(api, app):
    scheduler = app.state.scheduler
    acc = (await api.post("/api/accounts", json=body(cron_enabled=True, cron_interval_minutes=10))).json()
    assert acc["cron_enabled"] is True and acc["cron_interval_minutes"] == 10
    assert acc["cron_url"] is None and acc["cron_effective_url"] == "http://nc.test/cron.php"
    assert scheduler.next_cron_time(acc["id"]) is not None

    data = (await api.patch(f"/api/accounts/{acc['id']}", json={"cron_url": " https://other/cron.php "})).json()
    assert data["cron_url"] == "https://other/cron.php" and data["cron_enabled"] is True

    data = (await api.patch(f"/api/accounts/{acc['id']}", json={"cron_enabled": False, "cron_url": ""})).json()
    assert data["cron_enabled"] is False and data["cron_url"] is None
    assert scheduler.next_cron_time(acc["id"]) is None

    await api.patch(f"/api/accounts/{acc['id']}", json={"cron_enabled": True})
    await api.delete(f"/api/accounts/{acc['id']}")
    assert scheduler.next_cron_time(acc["id"]) is None


async def test_api_rejects_invalid_interval(api):
    assert (await api.post("/api/accounts", json=body(cron_interval_minutes=0))).status_code == 422


async def test_api_run_cron_now(api, dav):
    server = dav("nc", nextcloud=True)
    acc = (await api.post("/api/accounts", json=body())).json()

    data = (await api.post(f"/api/accounts/{acc['id']}/cron")).json()

    assert server.cron_calls == 1
    assert data["cron_last_ok"] is True and data["cron_last_run_at"] is not None
    assert (await api.post("/api/accounts/99/cron")).status_code == 404
