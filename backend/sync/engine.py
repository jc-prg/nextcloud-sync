"""Core sync engine: compare two WebDAV trees and apply changes."""

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

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
        files_excluded = 0
        exclusion = _Exclusion(rule)
        # Destination dirs that could not be created → number of entries skipped below them
        failed_dirs: dict[str, int] = {}

        # --- Sync source → destination ---
        for rel, src_entry in src_map.items():
            dst_path = rule.dest_path.rstrip("/") + "/" + rel.lstrip("/")
            src_path = rule.source_path.rstrip("/") + "/" + rel.lstrip("/")

            # Skip entries inside excluded subfolders
            if exclusion.is_subfolder_excluded(rel):
                if not src_entry.is_dir:
                    files_excluded += 1
                continue

            # Skip entries inside folders excluded by name (e.g. node_modules) at any depth
            if exclusion.is_folder_name_excluded(rel, src_entry.is_dir):
                if not src_entry.is_dir:
                    files_excluded += 1
                continue

            # Skip hidden files/directories (any path component starting with '.')
            if exclusion.is_hidden_path(rel):
                if not src_entry.is_dir:
                    files_excluded += 1
                continue

            # Skip everything below a dir that could not be created — it would only fail too
            failed_parent = _failed_ancestor(rel, failed_dirs)
            if failed_parent is not None:
                failed_dirs[failed_parent] += 1
                continue

            if src_entry.is_dir:
                if rel not in dst_map:
                    try:
                        await dst.mkcol(dst_path)
                        await _log(db, job.id, LogLevel.info, f"Created dir: {dst_path}", dst_path)
                    except Exception as exc:
                        await _log(db, job.id, LogLevel.error, f"Failed to create dir {dst_path}: {_exc_detail(exc)}", dst_path)
                        failed_dirs[rel] = 0
                        has_error = True
                continue

            # Apply exclusion filters
            excluded, reason = exclusion.check(src_entry)
            if excluded:
                files_excluded += 1
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
                await src.copy_to(src_path, dst, dst_path, src_entry.size)
                job.bytes_transferred += src_entry.size
                await _log(db, job.id, LogLevel.info, f"{verb}: {rel}", rel)
            except Exception as exc:
                job.files_added -= 1 if verb == "Added" else 0
                job.files_updated -= 1 if verb == "Updated" else 0
                await _log(db, job.id, LogLevel.error, f"Failed to copy {rel}: {_exc_detail(exc)}", rel)
                has_error = True

        for rel, skipped in failed_dirs.items():
            if skipped:
                await _log(
                    db, job.id, LogLevel.warning,
                    f"Skipped {skipped} entries below {rel} because the folder could not be created", rel,
                )

        # --- Delete orphans on destination ---
        if rule.delete_orphans:
            for rel in list(dst_map):
                is_excluded_root = (
                    exclusion.is_excluded_subfolder_root(rel)
                    or exclusion.is_excluded_folder_name_root(rel, dst_map[rel].is_dir)
                )
                # Children of excluded folders: skip — deleting the root dir handles them recursively
                is_excluded = exclusion.is_subfolder_excluded(rel) or exclusion.is_folder_name_excluded(rel, dst_map[rel].is_dir)
                if is_excluded and not is_excluded_root:
                    continue
                # Delete if: true orphan (not on source) OR root of an excluded folder
                if rel not in src_map or is_excluded_root:
                    dst_path = rule.dest_path.rstrip("/") + "/" + rel.lstrip("/")
                    try:
                        await dst.delete(dst_path)
                        job.files_deleted += 1
                        await _log(db, job.id, LogLevel.info, f"Deleted: {rel}", rel)
                    except Exception as exc:
                        await _log(db, job.id, LogLevel.error, f"Failed to delete {rel}: {_exc_detail(exc)}", rel)
                        has_error = True

        # --- Two-way: sync destination → source ---
        if rule.direction == SyncDirection.two_way:
            for rel, dst_entry in dst_map.items():
                if dst_entry.is_dir or rel in src_map:
                    continue
                src_path = rule.source_path.rstrip("/") + "/" + rel.lstrip("/")
                dst_path = rule.dest_path.rstrip("/") + "/" + rel.lstrip("/")
                try:
                    await dst.copy_to(dst_path, src, src_path, dst_entry.size)
                    job.files_added += 1
                    job.bytes_transferred += dst_entry.size
                    await _log(db, job.id, LogLevel.info, f"Added (from dest): {rel}", rel)
                except Exception as exc:
                    await _log(db, job.id, LogLevel.error, f"Failed reverse copy {rel}: {_exc_detail(exc)}", rel)
                    has_error = True

        final_status = JobStatus.partial if has_error else JobStatus.success
        await _finish_job(db, rule, job, final_status)
        await _log(
            db, job.id, LogLevel.info,
            f"Done — added:{job.files_added} updated:{job.files_updated} "
            f"deleted:{job.files_deleted} excluded:{files_excluded} bytes:{job.bytes_transferred}"
        )


class _Exclusion:
    """Pre-compiled exclusion filters for a sync rule."""

    def __init__(self, rule: SyncRule) -> None:
        raw = rule.exclude_patterns
        patterns = json.loads(raw) if raw else []
        self._regexes = [re.compile(p) for p in patterns]
        self._min = rule.min_file_size
        self._max = rule.max_file_size
        self._exclude_hidden = rule.exclude_hidden
        raw_sf = rule.exclude_subfolders
        subfolders = json.loads(raw_sf) if raw_sf else []
        # Strip source_path prefix (SubfolderPicker stores absolute WebDAV paths)
        # then normalise to "/subfolder" to match the relative keys in src_map/dst_map
        src_prefix = rule.source_path.rstrip("/")
        rel_subfolders = []
        for s in subfolders:
            s = s.rstrip("/")
            if s.startswith(src_prefix):
                s = s[len(src_prefix):]
            rel_subfolders.append("/" + s.strip("/"))
        self._excluded_subfolders = rel_subfolders
        raw_fn = rule.exclude_folder_names
        self._excluded_folder_names = {n.strip().strip("/") for n in (json.loads(raw_fn) if raw_fn else []) if n.strip()}

    def is_subfolder_excluded(self, rel: str) -> bool:
        """Return True if rel path is inside (or is) an excluded subfolder."""
        for sf in self._excluded_subfolders:
            if rel == sf or rel.startswith(sf + "/"):
                return True
        return False

    def is_excluded_subfolder_root(self, rel: str) -> bool:
        """Return True if rel is the root of an excluded subfolder (not a child)."""
        return rel in self._excluded_subfolders

    def _folder_parts(self, rel: str, is_dir: bool) -> list[str]:
        parts = [p for p in rel.strip("/").split("/") if p]
        return parts if is_dir else parts[:-1]

    def is_folder_name_excluded(self, rel: str, is_dir: bool) -> bool:
        """Return True if rel is, or lies inside, a folder whose name is excluded."""
        if not self._excluded_folder_names:
            return False
        return any(p in self._excluded_folder_names for p in self._folder_parts(rel, is_dir))

    def is_excluded_folder_name_root(self, rel: str, is_dir: bool) -> bool:
        """Return True if rel is the outermost folder excluded by name (not a child of one)."""
        if not is_dir or not self._excluded_folder_names:
            return False
        parts = self._folder_parts(rel, is_dir)
        return (
            parts[-1] in self._excluded_folder_names
            and not any(p in self._excluded_folder_names for p in parts[:-1])
        )

    def is_hidden_path(self, rel: str) -> bool:
        """Return True if any component of the relative path matches hidden/temp patterns."""
        if not self._exclude_hidden:
            return False
        for part in rel.strip("/").split("/"):
            if not part:
                continue
            if part.startswith(".") or "~" in part or part.lower().endswith((".bak", ".tmp")):
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


_SABRE_NS = "{http://sabredav.org/ns}"


def _exc_detail(exc: Exception) -> str:
    """Return a descriptive error string for the sync log.

    For HTTP errors this includes the request method and URL, any redirects that
    were followed, identifying response headers and a readable excerpt of the
    body, so it is visible *which* component (DAV, web frontend, proxy) answered.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        resp = exc.response
        req = resp.request
        detail = f"HTTP {resp.status_code} {resp.reason_phrase} for {req.method} {req.url}"
        if resp.history:
            hops = " → ".join(
                f"{r.status_code} {r.request.method} {r.request.url}" for r in resp.history
            )
            detail += f" (redirected: {hops})"
        headers = [
            f"{name}={resp.headers[name]}"
            for name in ("content-type", "server", "x-request-id", "x-powered-by")
            if name in resp.headers
        ]
        if headers:
            detail += f" [{', '.join(headers)}]"
        body = _body_excerpt(resp)
        if body:
            detail += f" — {body}"
        return detail
    if isinstance(exc, httpx.TimeoutException):
        return f"Timeout ({type(exc).__name__})"
    if isinstance(exc, httpx.ConnectError):
        return f"Connection error: {exc}"
    return str(exc)


def _body_excerpt(resp: httpx.Response, limit: int = 300) -> str:
    """Extract the meaningful part of an error body: Sabre exception + message
    for DAV errors, the page title + visible text for HTML pages."""
    try:
        body = resp.text.strip()
    except Exception:
        return ""
    if not body:
        return ""
    if "sabredav.org/ns" in body:
        try:
            root = ET.fromstring(body)
            exc_el = root.find(f"{_SABRE_NS}exception")
            msg_el = root.find(f"{_SABRE_NS}message")
            parts = [el.text.strip() for el in (exc_el, msg_el) if el is not None and el.text]
            if parts:
                return ": ".join(parts)
        except ET.ParseError:
            pass
    if "<html" in body[:500].lower():
        title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
        text = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        prefix = f"HTML page '{title.group(1).strip()}': " if title else "HTML page: "
        body = prefix + text
    else:
        body = re.sub(r"\s+", " ", body)
    return body[:limit] + "…" if len(body) > limit else body
    if isinstance(exc, httpx.TimeoutException):
        return f"Timeout ({type(exc).__name__})"
    if isinstance(exc, httpx.ConnectError):
        return f"Connection error: {exc}"
    return str(exc)


def _failed_ancestor(rel: str, failed_dirs: dict[str, int]) -> str | None:
    """Return the failed dir that rel lies below, if any."""
    for d in failed_dirs:
        if rel.startswith(d + "/"):
            return d
    return None


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
