"""Core sync engine: compare two WebDAV trees and apply changes."""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.crypto import decrypt
from backend.database import SessionLocal
from backend.models import Account, JobStatus, LogLevel, SyncDirection, SyncJob, SyncLog, SyncRule
from backend.sync.webdav import DavEntry, WebDAVClient

logger = logging.getLogger(__name__)

# Maps job_id → running asyncio.Task so abort_job() can cancel it
_running: dict[int, asyncio.Task] = {}


def abort_job(job_id: int) -> bool:
    """Request cancellation of a running sync job. Returns True if found."""
    task = _running.get(job_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def running_job_ids() -> list[int]:
    return [jid for jid, t in _running.items() if not t.done()]


async def run_sync(rule_id: int) -> None:
    """Entry point called by the scheduler. Opens its own DB session."""
    async with SessionLocal() as db:
        result = await db.execute(
            select(SyncRule)
            .where(SyncRule.id == rule_id)
            .join(SyncRule.source_account)
        )
        rule = result.scalar_one_or_none()
        if rule is None:
            logger.error("SyncRule %d not found", rule_id)
            return

        src_acc = await db.get(Account, rule.source_account_id)
        dst_acc = await db.get(Account, rule.dest_account_id)

        job = SyncJob(sync_rule_id=rule.id, status=JobStatus.running)
        db.add(job)
        await db.commit()
        await db.refresh(job)

        _running[job.id] = asyncio.current_task()
        aborted = False
        try:
            await _execute_sync(db, job, rule, src_acc, dst_acc)
        except asyncio.CancelledError:
            aborted = True
        except Exception as exc:
            logger.exception("Unhandled error in sync job %d", job.id)
            await _finish_job(db, rule, job, JobStatus.error)
            await _log(db, job.id, LogLevel.error, f"Fatal error: {exc}")
        finally:
            _running.pop(job.id, None)
            if aborted:
                await _finish_job(db, rule, job, JobStatus.aborted)
                await _log(db, job.id, LogLevel.warning, "Job aborted by user")
            rule.last_run_at = datetime.now(timezone.utc)
            await db.commit()


async def _execute_sync(
    db: AsyncSession,
    job: SyncJob,
    rule: SyncRule,
    src_acc: Account,
    dst_acc: Account,
) -> None:
    src_pass = decrypt(src_acc.password_enc)
    dst_pass = decrypt(dst_acc.password_enc)

    async with (
        WebDAVClient(src_acc.webdav_url, src_acc.username, src_pass) as src,
        WebDAVClient(dst_acc.webdav_url, dst_acc.username, dst_pass) as dst,
    ):
        await _log(db, job.id, LogLevel.info, f"Listing source: {src_acc.webdav_url}{rule.source_path}")
        src_tree = await src.propfind(rule.source_path, depth="infinity")  # type: ignore[arg-type]
        await _log(db, job.id, LogLevel.info, f"Listing destination: {dst_acc.webdav_url}{rule.dest_path}")
        dst_tree = await dst.propfind(rule.dest_path, depth="infinity")  # type: ignore[arg-type]

        # Build lookup maps: relative-path → DavEntry (relative to sync root)
        src_map = _build_map(src_tree, rule.source_path)
        dst_map = _build_map(dst_tree, rule.dest_path)

        has_error = False
        exclusion = _Exclusion(rule)

        # --- Sync source → destination ---
        for rel, src_entry in src_map.items():
            dst_path = rule.dest_path.rstrip("/") + "/" + rel.lstrip("/")
            src_path = rule.source_path.rstrip("/") + "/" + rel.lstrip("/")

            # Skip entries inside excluded subfolders
            if exclusion.is_subfolder_excluded(rel):
                continue

            if src_entry.is_dir:
                if rel not in dst_map:
                    try:
                        await dst.mkcol(dst_path)
                        await _log(db, job.id, LogLevel.info, f"Created dir: {dst_path}", dst_path)
                    except Exception as exc:
                        await _log(db, job.id, LogLevel.error, f"Failed to create dir {dst_path}: {exc}", dst_path)
                        has_error = True
                continue

            # Apply exclusion filters
            excluded, reason = exclusion.check(src_entry)
            if excluded:
                await _log(db, job.id, LogLevel.info, f"Skipped: {rel} ({reason})", rel)
                continue

            # File: copy if missing or changed
            if rel in dst_map:
                if not _is_changed(src_entry, dst_map[rel]):
                    continue
                verb = "Updated"
                job.files_updated += 1
            else:
                verb = "Added"
                job.files_added += 1

            try:
                data = await src.get_bytes(src_path)
                await dst.put_bytes(dst_path, data)
                job.bytes_transferred += len(data)
                await _log(db, job.id, LogLevel.info, f"{verb}: {rel}", rel)
            except Exception as exc:
                job.files_added -= 1 if verb == "Added" else 0
                job.files_updated -= 1 if verb == "Updated" else 0
                await _log(db, job.id, LogLevel.error, f"Failed to copy {rel}: {exc}", rel)
                has_error = True

        # --- Delete orphans on destination ---
        if rule.delete_orphans:
            for rel in list(dst_map):
                if rel not in src_map:
                    dst_path = rule.dest_path.rstrip("/") + "/" + rel.lstrip("/")
                    try:
                        await dst.delete(dst_path)
                        job.files_deleted += 1
                        await _log(db, job.id, LogLevel.info, f"Deleted: {rel}", rel)
                    except Exception as exc:
                        await _log(db, job.id, LogLevel.error, f"Failed to delete {rel}: {exc}", rel)
                        has_error = True

        # --- Two-way: sync destination → source ---
        if rule.direction == SyncDirection.two_way:
            for rel, dst_entry in dst_map.items():
                if dst_entry.is_dir or rel in src_map:
                    continue
                src_path = rule.source_path.rstrip("/") + "/" + rel.lstrip("/")
                dst_path = rule.dest_path.rstrip("/") + "/" + rel.lstrip("/")
                try:
                    data = await dst.get_bytes(dst_path)
                    await src.put_bytes(src_path, data)
                    job.files_added += 1
                    job.bytes_transferred += len(data)
                    await _log(db, job.id, LogLevel.info, f"Added (from dest): {rel}", rel)
                except Exception as exc:
                    await _log(db, job.id, LogLevel.error, f"Failed reverse copy {rel}: {exc}", rel)
                    has_error = True

        final_status = JobStatus.partial if has_error else JobStatus.success
        await _finish_job(db, rule, job, final_status)
        await _log(
            db, job.id, LogLevel.info,
            f"Done — added:{job.files_added} updated:{job.files_updated} "
            f"deleted:{job.files_deleted} bytes:{job.bytes_transferred}"
        )


class _Exclusion:
    """Pre-compiled exclusion filters for a sync rule."""

    def __init__(self, rule: SyncRule) -> None:
        raw = rule.exclude_patterns
        patterns = json.loads(raw) if raw else []
        self._regexes = [re.compile(p) for p in patterns]
        self._min = rule.min_file_size
        self._max = rule.max_file_size
        raw_sf = rule.exclude_subfolders
        # Normalise to "/subfolder" so prefix checks are consistent
        subfolders = json.loads(raw_sf) if raw_sf else []
        self._excluded_subfolders = ["/" + s.strip("/") for s in subfolders]

    def is_subfolder_excluded(self, rel: str) -> bool:
        """Return True if rel path is inside (or is) an excluded subfolder."""
        for sf in self._excluded_subfolders:
            if rel == sf or rel.startswith(sf + "/"):
                return True
        return False

    def check(self, entry: DavEntry) -> tuple[bool, str]:
        """Return (excluded, reason). Only applied to files, not directories."""
        if self._max is not None and entry.size > self._max:
            return True, f"size {_fmt_bytes(entry.size)} exceeds max {_fmt_bytes(self._max)}"
        if self._min is not None and entry.size < self._min:
            return True, f"size {_fmt_bytes(entry.size)} below min {_fmt_bytes(self._min)}"
        for rx in self._regexes:
            if rx.search(entry.name):
                return True, f"matches pattern {rx.pattern!r}"
        return False, ""


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _build_map(entries: list[DavEntry], root_path: str) -> dict[str, DavEntry]:
    """Return {relative_path: entry} stripping the sync root prefix."""
    prefix = root_path.rstrip("/")
    result: dict[str, DavEntry] = {}
    for e in entries:
        rel = e.rel_path
        if rel.rstrip("/") == prefix:
            continue  # skip the root itself
        if rel.startswith(prefix + "/"):
            rel = rel[len(prefix):]
        result[rel.rstrip("/")] = e
    return result


def _is_changed(src: DavEntry, dst: DavEntry) -> bool:
    """Return True if the file on source differs from destination.

    ETags are intentionally NOT compared: Nextcloud generates server-specific
    ETags (based on internal node IDs), so the same file on two different
    Nextcloud instances will always have different ETags even with identical
    content. We rely on size + mtime instead.
    """
    if src.size != dst.size:
        return True
    if src.mtime and dst.mtime:
        return src.mtime > dst.mtime
    return False


async def _log(db: AsyncSession, job_id: int, level: LogLevel, message: str, path: str | None = None) -> None:
    entry = SyncLog(sync_job_id=job_id, level=level, message=message, path=path)
    db.add(entry)
    await db.commit()


async def _finish_job(db: AsyncSession, rule: SyncRule, job: SyncJob, status: JobStatus) -> None:
    job.status = status
    job.finished_at = datetime.now(timezone.utc)
    await db.commit()
