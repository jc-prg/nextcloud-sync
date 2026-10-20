"""Two-way sync with the .next-sync state file, through run_sync()."""

import json

import pytest

from backend.models import JobStatus, SyncDirection
from backend.sync.engine import STATE_FILE
from backend.tests.factories import make_account, make_rule, sync, update_rule

STATE = "/sync/" + STATE_FILE


@pytest.fixture
async def setup(dav):
    src, dst = dav("src"), dav("dst")
    src.mkdir("/sync")
    dst.mkdir("/sync")
    src_acc = await make_account(src, "source")
    dst_acc = await make_account(dst, "dest")

    async def rule(**fields):
        values = dict(direction=SyncDirection.two_way, delete_orphans=True)
        values.update(fields)
        return await make_rule(src_acc, dst_acc, **values)

    return src, dst, rule


def content(server) -> dict:
    """The synced tree without the state file."""
    return {p: c for p, c in server.tree("/sync").items() if p != "/" + STATE_FILE}


async def ok(rule_id: int):
    """Run a sync that must not fail."""
    job, logs = await sync(rule_id)
    assert job.status == JobStatus.success, logs
    return job, logs


async def test_first_run_merges_both_sides_without_deleting(setup):
    src, dst, rule = setup
    src.write("/sync/a/1.txt", "1")
    dst.write("/sync/b/2.txt", "2")
    r = await rule()

    job, logs = await ok(r.id)

    expected = {"/a": None, "/a/1.txt": b"1", "/b": None, "/b/2.txt": b"2"}
    assert content(src) == content(dst) == expected
    assert job.files_deleted == 0
    assert "No previous sync state — nothing will be deleted in this run" in logs
    assert src.exists(STATE) and dst.exists(STATE)


async def test_state_file_contents(setup):
    src, dst, rule = setup
    src.write("/sync/a/1.txt", "1")
    src.write("/sync/.hidden", "h")
    r = await rule()
    await ok(r.id)

    doc = json.loads(src.read(STATE))
    assert doc == json.loads(dst.read(STATE))
    state = doc["rules"][str(r.id)]
    assert (state["source_path"], state["dest_path"]) == ("/sync", "/sync")
    assert set(state["entries"]) == {"/a", "/a/1.txt"}  # excluded entries are not recorded
    assert state["entries"]["/a/1.txt"]["dir"] is False


async def test_idle_run_transfers_nothing(setup):
    src, dst, rule = setup
    src.write("/sync/a.txt", "a")
    dst.write("/sync/b.txt", "b")
    r = await rule()
    await ok(r.id)

    job, _ = await ok(r.id)

    assert (job.files_added, job.files_updated, job.files_deleted, job.bytes_transferred) == (0, 0, 0, 0)


async def test_file_copied_back_to_source_is_not_uploaded_again(setup):
    src, dst, rule = setup
    dst.write("/sync/from_dst.txt", "d")
    r = await rule()
    await ok(r.id)
    puts_before = dst.count("PUT")

    job, logs = await ok(r.id)

    assert job.files_updated == 0, logs
    assert dst.count("PUT") == puts_before + 1  # only the state file


async def test_deletions_propagate_in_both_directions(setup):
    src, dst, rule = setup
    src.write("/sync/dir/a.txt", "a")
    src.write("/sync/dir/sub/b.txt", "b")
    src.write("/sync/s.txt", "s")
    dst.write("/sync/d.txt", "d")
    r = await rule()
    await ok(r.id)

    src.rm("/sync/dir")
    dst.rm("/sync/s.txt")
    job, logs = await ok(r.id)

    assert content(src) == content(dst) == {"/d.txt": b"d"}
    assert job.files_deleted == 2
    assert "Deleted: /dir" in logs and "Deleted from source: /s.txt" in logs
    assert dst.count("DELETE") == 1 and src.count("DELETE") == 1


async def test_folder_deleted_on_destination_is_deleted_on_source(setup):
    src, dst, rule = setup
    src.write("/sync/dir/a/b.txt", "b")
    r = await rule()
    await ok(r.id)

    dst.rm("/sync/dir")
    job, _ = await ok(r.id)

    assert content(src) == content(dst) == {}
    assert job.files_deleted == 1 and src.count("DELETE") == 1


async def test_new_files_propagate_in_both_directions(setup):
    src, dst, rule = setup
    r = await rule()
    await ok(r.id)

    src.write("/sync/new/s.txt", "s")
    dst.write("/sync/other/d.txt", "d")
    job, logs = await ok(r.id)

    expected = {"/new": None, "/new/s.txt": b"s", "/other": None, "/other/d.txt": b"d"}
    assert content(src) == content(dst) == expected
    assert "Created dir on source: /sync/other" in logs and "Added (from dest): /other/d.txt" in logs


async def test_edits_propagate_in_both_directions(setup):
    src, dst, rule = setup
    src.write("/sync/a.txt", "a")
    src.write("/sync/b.txt", "b")
    r = await rule()
    await ok(r.id)

    src.write("/sync/a.txt", "a2")
    dst.write("/sync/b.txt", "b2")
    job, logs = await ok(r.id)

    assert content(src) == content(dst) == {"/a.txt": b"a2", "/b.txt": b"b2"}
    assert job.files_updated == 2
    assert "Updated: /a.txt" in logs and "Updated (from dest): /b.txt" in logs

    job, _ = await ok(r.id)
    assert job.files_updated == 0


async def test_conflict_is_reported_until_resolved(setup):
    src, dst, rule = setup
    src.write("/sync/c.txt", "base")
    r = await rule()
    await ok(r.id)

    src.write("/sync/c.txt", "source edit")
    dst.write("/sync/c.txt", "destination edit")
    for _ in range(2):
        job, logs = await sync(r.id)
        assert job.status == JobStatus.partial
        assert any(m.startswith("Conflict: /c.txt was changed on both") for m in logs)
        assert src.read("/sync/c.txt") == b"source edit"
        assert dst.read("/sync/c.txt") == b"destination edit"

    # Resolve by deleting the unwanted version: the other one is copied over
    dst.rm("/sync/c.txt")
    job, logs = await ok(r.id)
    assert dst.read("/sync/c.txt") == b"source edit"
    assert not any("Conflict" in m for m in logs)


async def test_identical_edits_are_not_a_conflict(setup):
    src, dst, rule = setup
    src.write("/sync/c.txt", "base")
    r = await rule()
    await ok(r.id)

    src.write("/sync/c.txt", "same")
    dst.write("/sync/c.txt", "same")
    job, logs = await ok(r.id)

    assert job.files_updated == 0
    job, logs = await ok(r.id)  # and the new state is recorded
    assert not any("Conflict" in m for m in logs)


async def test_file_versus_folder_is_a_conflict(setup):
    src, dst, rule = setup
    src.write("/sync/t", "file")
    dst.write("/sync/t/inner.txt", "i")
    r = await rule()

    job, logs = await sync(r.id)

    assert job.status == JobStatus.partial
    assert "Conflict: /t is a file on the source but a folder on the destination — left unchanged" in logs
    assert src.read("/sync/t") == b"file"
    assert dst.read("/sync/t/inner.txt") == b"i"


async def test_deleted_on_one_side_but_modified_on_the_other_is_kept(setup):
    src, dst, rule = setup
    src.write("/sync/dir/x.txt", "x")
    r = await rule()
    await ok(r.id)

    dst.rm("/sync/dir")
    src.write("/sync/dir/x.txt", "modified")
    job, _ = await ok(r.id)

    assert content(src) == content(dst) == {"/dir": None, "/dir/x.txt": b"modified"}
    assert job.files_deleted == 0


async def test_deleted_folder_with_new_content_on_the_other_side_keeps_only_new_content(setup):
    src, dst, rule = setup
    src.write("/sync/dir/old.txt", "o")
    r = await rule()
    await ok(r.id)

    dst.rm("/sync/dir")
    src.write("/sync/dir/new.txt", "n")
    await ok(r.id)

    assert content(src) == content(dst) == {"/dir": None, "/dir/new.txt": b"n"}


async def test_without_delete_orphans_nothing_is_deleted(setup):
    src, dst, rule = setup
    src.write("/sync/a.txt", "a")
    r = await rule(delete_orphans=False)
    await ok(r.id)

    src.rm("/sync/a.txt")
    job, _ = await ok(r.id)

    assert job.files_deleted == 0
    assert src.read("/sync/a.txt") == b"a"  # copied back from the destination


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
async def test_missing_or_corrupt_state_deletes_nothing(setup, damage):
    src, dst, rule = setup
    src.write("/sync/a.txt", "a")
    r = await rule()
    await ok(r.id)

    if damage == "missing":
        dst.rm(STATE)
    else:
        dst.write(STATE, "{not json")
    src.rm("/sync/a.txt")
    job, logs = await ok(r.id)

    assert job.files_deleted == 0
    assert src.read("/sync/a.txt") == b"a"
    if damage == "corrupt":
        assert any(m.startswith("Ignoring unreadable sync state on destination") for m in logs)


async def test_state_is_ignored_when_rule_paths_change(setup):
    src, dst, rule = setup
    src.write("/sync/a.txt", "a")
    src.mkdir("/other")
    r = await rule()
    await ok(r.id)

    # Same rule id, different destination: the old record must not drive deletions
    dst.write("/other/a.txt", "a")
    await update_rule(r.id, dest_path="/other")
    dst.write("/other/" + STATE_FILE, dst.read(STATE))
    src.rm("/sync/a.txt")
    job, _ = await ok(r.id)

    assert job.files_deleted == 0


async def test_rules_sharing_a_root_keep_separate_state(setup, dav):
    src, dst, rule = setup
    third = dav("third")
    third.mkdir("/sync")
    src.write("/sync/a.txt", "a")
    r1 = await rule()
    r2 = await make_rule(await make_account(src, "s2"), await make_account(third, "t"),
                         direction=SyncDirection.two_way, delete_orphans=True)

    await ok(r1.id)
    await ok(r2.id)

    assert set(json.loads(src.read(STATE))["rules"]) == {str(r1.id), str(r2.id)}
    assert set(json.loads(dst.read(STATE))["rules"]) == {str(r1.id)}


async def test_state_file_is_never_synced(setup):
    src, dst, rule = setup
    src.write("/sync/a.txt", "a")
    r = await rule(exclude_hidden=False)
    await ok(r.id)
    job, logs = await ok(r.id)

    assert not any(STATE_FILE in m for m in logs)
    assert json.loads(src.read(STATE))["rules"].keys() == json.loads(dst.read(STATE))["rules"].keys()


async def test_failing_state_write_marks_job_partial(setup):
    src, dst, rule = setup
    dst.fail("PUT", STATE, 507)
    r = await rule()

    job, logs = await sync(r.id)

    assert job.status == JobStatus.partial
    assert any(m.startswith("Failed to write sync state on destination") for m in logs)
