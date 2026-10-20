"""One-way sync through run_sync(), against two in-memory WebDAV servers."""

import json

import pytest

from backend.database import SessionLocal
from backend.models import JobStatus, SyncRule
from backend.tests.factories import make_account, make_rule, sync


@pytest.fixture
async def setup(dav):
    """Source and destination servers with an empty /sync root, plus a rule factory."""
    src, dst = dav("src"), dav("dst")
    src.mkdir("/sync")
    dst.mkdir("/sync")
    src_acc = await make_account(src, "source")
    dst_acc = await make_account(dst, "dest")

    async def rule(**fields):
        return await make_rule(src_acc, dst_acc, **fields)

    return src, dst, rule


async def test_copies_new_files_and_folders(setup):
    src, dst, rule = setup
    src.write("/sync/a.txt", "a")
    src.write("/sync/dir/sub/b.txt", "bb")
    r = await rule()

    job, logs = await sync(r.id)

    assert job.status == JobStatus.success
    assert dst.tree("/sync") == {"/a.txt": b"a", "/dir": None, "/dir/sub": None, "/dir/sub/b.txt": b"bb"}
    assert (job.files_added, job.files_updated, job.files_deleted, job.bytes_transferred) == (2, 0, 0, 3)
    assert "Added: /a.txt" in logs and "Created dir: /sync/dir" in logs
    assert logs[-1].startswith("Done — added:2")
    # One-way never writes the two-way state file
    assert not src.exists("/sync/.next-sync") and not dst.exists("/sync/.next-sync")
    async with SessionLocal() as db:
        assert (await db.get(SyncRule, r.id)).last_run_at is not None


async def test_second_run_without_changes_transfers_nothing(setup):
    src, dst, rule = setup
    src.write("/sync/a.txt", "a")
    r = await rule()
    await sync(r.id)

    job, _ = await sync(r.id)

    assert (job.files_added, job.files_updated, job.bytes_transferred) == (0, 0, 0)
    assert dst.count("PUT") == 1


async def test_updates_changed_files(setup):
    src, dst, rule = setup
    src.write("/sync/a.txt", "a")
    r = await rule()
    await sync(r.id)
    src.write("/sync/a.txt", "changed")

    job, logs = await sync(r.id)

    assert dst.read("/sync/a.txt") == b"changed"
    assert job.files_updated == 1 and "Updated: /a.txt" in logs


async def test_orphans_are_kept_without_delete_orphans(setup):
    src, dst, rule = setup
    dst.write("/sync/extra.txt", "x")
    r = await rule(delete_orphans=False)

    job, _ = await sync(r.id)

    assert dst.exists("/sync/extra.txt") and job.files_deleted == 0


async def test_orphans_are_deleted_with_delete_orphans(setup):
    src, dst, rule = setup
    src.write("/sync/keep.txt", "k")
    dst.write("/sync/keep.txt", "k")
    dst.write("/sync/extra.txt", "x")
    r = await rule(delete_orphans=True)

    job, logs = await sync(r.id)

    assert dst.tree("/sync") == {"/keep.txt": b"k"}
    assert job.files_deleted == 1 and "Deleted: /extra.txt" in logs


async def test_contents_of_a_deleted_folder_are_not_deleted_again(setup):
    """Regression: deleting /old must not be followed by DELETEs of /old/... (404 errors)."""
    src, dst, rule = setup
    dst.write("/sync/old/a/b/c.txt", "c")
    dst.write("/sync/old/d.txt", "d")
    r = await rule(delete_orphans=True)

    job, logs = await sync(r.id)

    assert job.status == JobStatus.success, logs
    assert not dst.exists("/sync/old")
    assert job.files_deleted == 1
    assert dst.count("DELETE") == 1


async def test_exclusion_filters(setup):
    src, dst, rule = setup
    for path in ["/keep.txt", "/debug.log", "/.hidden", "/big.bin", "/skip/x.txt", "/a/node_modules/m.js"]:
        src.write("/sync" + path, "x" * (50 if path == "/big.bin" else 1))
    r = await rule(
        exclude_patterns=json.dumps([r"\.log$"]),
        exclude_subfolders=json.dumps(["/sync/skip"]),
        exclude_folder_names=json.dumps(["node_modules"]),
        max_file_size=10,
    )

    job, logs = await sync(r.id)

    assert dst.tree("/sync") == {"/keep.txt": b"x", "/a": None}
    assert "excluded:5" in logs[-1]
    assert any(m.startswith("Skipped: /debug.log (matches pattern") for m in logs)
    assert any(m.startswith("Skipped: /big.bin (size") for m in logs)


async def test_excluded_folders_are_removed_from_the_destination(setup):
    src, dst, rule = setup
    src.write("/sync/skip/x.txt", "x")
    src.write("/sync/a/node_modules/m.js", "m")
    dst.write("/sync/skip/x.txt", "x")
    dst.write("/sync/a/node_modules/m.js", "m")
    r = await rule(
        delete_orphans=True,
        exclude_subfolders=json.dumps(["/sync/skip"]),
        exclude_folder_names=json.dumps(["node_modules"]),
    )

    job, logs = await sync(r.id)

    assert job.status == JobStatus.success, logs
    assert dst.tree("/sync") == {"/a": None}
    assert job.files_deleted == 2


async def test_folder_that_cannot_be_created_skips_its_contents(setup):
    src, dst, rule = setup
    src.write("/sync/bad/one.txt", "1")
    src.write("/sync/bad/sub/two.txt", "2")
    src.write("/sync/good.txt", "g")
    dst.fail("MKCOL", "/sync/bad", 403)
    r = await rule()

    job, logs = await sync(r.id)

    assert job.status == JobStatus.partial
    assert dst.tree("/sync") == {"/good.txt": b"g"}
    assert any(m.startswith("Failed to create dir /sync/bad: HTTP 403") for m in logs)
    assert "Skipped 3 entries below /bad because the folder could not be created" in logs
    # Nothing below it was even attempted
    assert dst.count("PUT") == 1


async def test_failing_file_marks_job_partial(setup):
    src, dst, rule = setup
    src.write("/sync/ok.txt", "o")
    src.write("/sync/fail.txt", "f")
    dst.fail("PUT", "/sync/fail.txt", 507)
    r = await rule()

    job, logs = await sync(r.id)

    assert job.status == JobStatus.partial
    assert job.files_added == 1
    assert any(m.startswith("Failed to copy /fail.txt: HTTP 507") for m in logs)


async def test_failing_delete_marks_job_partial(setup):
    src, dst, rule = setup
    dst.write("/sync/extra.txt", "x")
    dst.fail("DELETE", "/sync/extra.txt", 423)
    r = await rule(delete_orphans=True)

    job, logs = await sync(r.id)

    assert job.status == JobStatus.partial and job.files_deleted == 0
    assert any(m.startswith("Failed to delete /extra.txt") for m in logs)


async def test_unreachable_source_is_a_fatal_error(setup):
    src, dst, rule = setup
    src.rm("/sync")
    r = await rule()

    job, logs = await sync(r.id)

    assert job.status == JobStatus.error and job.finished_at is not None
    assert any(m.startswith("Fatal error:") for m in logs)


async def test_unknown_rule_is_ignored():
    from backend.sync.engine import run_sync

    await run_sync(999)  # logs an error, must not raise
