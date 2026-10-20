"""/api/rules, including the scheduler side effects."""

import asyncio

import pytest

from backend.sync import scheduler as scheduler_module
from backend.tests.factories import make_account


@pytest.fixture
async def accounts():
    return await make_account(label="src"), await make_account(label="dst")


@pytest.fixture
def jobs(app):
    """Look up a job of the app's scheduler by id."""
    return app.state.scheduler._scheduler.get_job


def body(accounts, **kw):
    src, dst = accounts
    values = dict(
        label="Photos", source_account_id=src.id, source_path="/Photos",
        dest_account_id=dst.id, dest_path="/Backup", schedule_cron="*/15 * * * *",
    )
    values.update(kw)
    return values


async def test_create_rule_with_defaults_and_schedule_it(api, accounts, jobs):
    resp = await api.post("/api/rules", json=body(accounts))

    assert resp.status_code == 201
    rule = resp.json()
    assert rule["direction"] == "one_way" and rule["enabled"] is True
    assert rule["delete_orphans"] is False and rule["exclude_hidden"] is True
    assert rule["exclude_patterns"] == [] and rule["last_run_at"] is None
    assert jobs(f"rule_{rule['id']}") is not None
    assert (await api.get(f"/api/rules/{rule['id']}")).json() == rule


async def test_list_fields_round_trip(api, accounts):
    lists = dict(
        exclude_patterns=[r"\.tmp$"], exclude_subfolders=["/Photos/raw"],
        exclude_folder_names=["node_modules"], known_subfolders=["/Photos/raw", "/Photos/2024"],
    )
    rule = (await api.post("/api/rules", json=body(accounts, **lists))).json()
    assert {k: rule[k] for k in lists} == lists

    rule = (await api.patch(f"/api/rules/{rule['id']}", json={"exclude_patterns": []})).json()
    assert rule["exclude_patterns"] == [] and rule["exclude_folder_names"] == ["node_modules"]


async def test_list_is_sorted_by_label(api, accounts):
    for label in ["b", "a"]:
        await api.post("/api/rules", json=body(accounts, label=label))
    assert [r["label"] for r in (await api.get("/api/rules")).json()] == ["a", "b"]


async def test_update_reschedules(api, accounts, jobs):
    rule = (await api.post("/api/rules", json=body(accounts))).json()

    resp = await api.patch(f"/api/rules/{rule['id']}", json={"schedule_cron": "0 3 * * *", "direction": "two_way"})

    assert resp.status_code == 200
    assert resp.json()["direction"] == "two_way" and resp.json()["label"] == "Photos"
    trigger = str(jobs(f"rule_{rule['id']}").trigger)
    assert "hour='3'" in trigger and "minute='0'" in trigger


async def test_disabling_unschedules(api, accounts, jobs):
    rule = (await api.post("/api/rules", json=body(accounts))).json()
    await api.patch(f"/api/rules/{rule['id']}", json={"enabled": False})
    assert jobs(f"rule_{rule['id']}") is None
    await api.patch(f"/api/rules/{rule['id']}", json={"enabled": True})
    assert jobs(f"rule_{rule['id']}") is not None


async def test_disabled_rule_is_not_scheduled_on_create(api, accounts, jobs):
    rule = (await api.post("/api/rules", json=body(accounts, enabled=False))).json()
    assert jobs(f"rule_{rule['id']}") is None


async def test_invalid_cron_is_stored_but_not_scheduled(api, accounts, jobs):
    resp = await api.post("/api/rules", json=body(accounts, schedule_cron="not a cron"))
    assert resp.status_code == 201
    assert jobs(f"rule_{resp.json()['id']}") is None


async def test_delete_unschedules(api, accounts, jobs):
    rule = (await api.post("/api/rules", json=body(accounts))).json()
    assert (await api.delete(f"/api/rules/{rule['id']}")).status_code == 204
    assert jobs(f"rule_{rule['id']}") is None
    assert (await api.get(f"/api/rules/{rule['id']}")).status_code == 404


async def test_run_now_triggers_a_sync(api, accounts, monkeypatch):
    started = asyncio.Event()
    ran = []

    async def fake_run_sync(rule_id):
        ran.append(rule_id)
        started.set()

    monkeypatch.setattr(scheduler_module, "run_sync", fake_run_sync)
    rule = (await api.post("/api/rules", json=body(accounts))).json()

    resp = await api.post(f"/api/rules/{rule['id']}/run")

    assert resp.status_code == 202
    await asyncio.wait_for(started.wait(), timeout=5)
    assert ran == [rule["id"]]


async def test_unknown_rule_is_404(api):
    assert (await api.get("/api/rules/99")).status_code == 404
    assert (await api.patch("/api/rules/99", json={})).status_code == 404
    assert (await api.delete("/api/rules/99")).status_code == 404
    assert (await api.post("/api/rules/99/run")).status_code == 404


async def test_invalid_body_is_422(api, accounts):
    assert (await api.post("/api/rules", json={"label": "x"})).status_code == 422
    assert (await api.post("/api/rules", json=body(accounts, direction="sideways"))).status_code == 422
