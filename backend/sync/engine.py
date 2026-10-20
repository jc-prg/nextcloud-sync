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

# Two-way sync state file, kept in the root of source and destination
STATE_FILE = ".next-sync"
STATE_REL = "/" + STATE_FILE
STATE_VERSION = 1
# Files changed on both sides are compared byte by byte up to this size — equal content is no conflict
SAME_CONTENT_MAX_BYTES = 32 * 1024 * 1024

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
        # The sync state files are bookkeeping, never synced themselves
        src_map.pop(STATE_REL, None)
        dst_map.pop(STATE_REL, None)

        two_way = rule.direction == SyncDirection.two_way
        has_error = False
        files_excluded = 0
        exclusion = _Exclusion(rule)
        # Destination dirs that could not be created → number of entries skipped below them
        failed_dirs: dict[str, int] = {}

        # Two-way: the state of the last run tells "new on one side" apart from
        # "deleted on the other side" for entries that exist on one side only
        known: dict[str, dict] = {}
        src_state_doc: dict = {}
        dst_state_doc: dict = {}
        src_dirty: set[str] = set()
        dst_dirty: set[str] = set()
        if two_way:
            src_state_doc = await _read_state(db, job.id, src, rule.source_path, "source")
            dst_state_doc = await _read_state(db, job.id, dst, rule.dest_path, "destination")
            known = _known_entries(rule, src_state_doc, dst_state_doc)
            src_dirty = _dirty_paths(src_map, known, "src")
            dst_dirty = _dirty_paths(dst_map, known, "dst")
            if not known:
                await _log(db, job.id, LogLevel.info, "No previous sync state — nothing will be deleted in this run")

        def deleted_elsewhere(rel: str, dirty: set[str]) -> bool:
            """Two-way: rel was synced last run, is gone on the other side and unchanged on this side."""
            return two_way and rule.delete_orphans and rel in known and rel not in dirty

        # Source dirs deleted because they were deleted on the destination
        src_deleted_dirs: list[str] = []
        # Two-way: entries changed on both sides since the last run — left untouched
        conflicts: set[str] = set()
        # Two-way: a dir on one side is a file on the other — nothing below it is synced
        conflict_dirs: list[str] = []

        # --- Sync source → destination ---
        # Sorted so parents come before their children
        for rel in sorted(src_map):
            src_entry = src_map[rel]
            dst_path = rule.dest_path.rstrip("/") + "/" + rel.lstrip("/")
            src_path = rule.source_path.rstrip("/") + "/" + rel.lstrip("/")

            if _under_any(rel, src_deleted_dirs) or _under_any(rel, conflict_dirs):
                continue

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

            # Two-way: deleted on the destination since the last run → delete on the source too
            if rel not in dst_map and deleted_elsewhere(rel, src_dirty):
                try:
                    await src.delete(src_path)
                    if src_entry.is_dir:
                        src_deleted_dirs.append(rel)
                    job.files_deleted += 1
                    await _log(db, job.id, LogLevel.info, f"Deleted from source: {rel}", rel)
                except Exception as exc:
                    await _log(db, job.id, LogLevel.error, f"Failed to delete {rel} from source: {_exc_detail(exc)}", rel)
                    has_error = True
                continue

            if two_way and rel in dst_map and dst_map[rel].is_dir != src_entry.is_dir:
                kinds = ("folder", "file") if src_entry.is_dir else ("file", "folder")
                await _log(
                    db, job.id, LogLevel.error,
                    f"Conflict: {rel} is a {kinds[0]} on the source but a {kinds[1]} on the destination — left unchanged",
                    rel,
                )
                conflicts.add(rel)
                conflict_dirs.append(rel)
                has_error = True
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
            if rel in dst_map and two_way:
                dst_entry = dst_map[rel]
                action = _two_way_action(src_entry, dst_entry, known.get(rel))
                if action == "conflict" and await _same_content(src, src_path, dst, dst_path, src_entry, dst_entry):
                    action = "none"
                if action == "none":
                    continue
                if action == "conflict":
                    await _log(
                        db, job.id, LogLevel.error,
                        f"Conflict: {rel} was changed on both source and destination since the last sync — "
                        "left unchanged; delete the unwanted version to resolve",
                        rel,
                    )
                    conflicts.add(rel)
                    has_error = True
                    continue
                if action == "to_src":
                    try:
                        await dst.copy_to(dst_path, src, src_path, dst_entry.size)
                        job.files_updated += 1
                        job.bytes_transferred += dst_entry.size
                        await _log(db, job.id, LogLevel.info, f"Updated (from dest): {rel}", rel)
                    except Exception as exc:
                        await _log(db, job.id, LogLevel.error, f"Failed reverse copy {rel}: {_exc_detail(exc)}", rel)
                        has_error = True
                    continue
                verb = "Updated"
                job.files_updated += 1
            elif rel in dst_map:
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
        # Destination entries deleted here (dirs take their contents with them)
        dst_deleted: set[str] = set()
        dst_deleted_dirs: list[str] = []
        if rule.delete_orphans:
            # Sorted so parents come before their children
            for rel in sorted(dst_map):
                if _under_any(rel, dst_deleted_dirs) or rel in conflicts or _under_any(rel, conflict_dirs):
                    continue
                is_excluded_root = (
                    exclusion.is_excluded_subfolder_root(rel)
                    or exclusion.is_excluded_folder_name_root(rel, dst_map[rel].is_dir)
                )
                # Children of excluded folders: skip — deleting the root dir handles them recursively
                is_excluded = exclusion.is_subfolder_excluded(rel) or exclusion.is_folder_name_excluded(rel, dst_map[rel].is_dir)
                if is_excluded and not is_excluded_root:
                    continue
                # One-way: every entry missing on the source is an orphan.
                # Two-way: only entries deleted on the source since the last run —
                # the others are new on the destination and get copied back below.
                is_orphan = rel not in src_map and (not two_way or deleted_elsewhere(rel, dst_dirty))
                if is_orphan or is_excluded_root:
                    dst_path = rule.dest_path.rstrip("/") + "/" + rel.lstrip("/")
                    try:
                        await dst.delete(dst_path)
                        dst_deleted.add(rel)
                        if dst_map[rel].is_dir:
                            dst_deleted_dirs.append(rel)
                        job.files_deleted += 1
                        await _log(db, job.id, LogLevel.info, f"Deleted: {rel}", rel)
                    except Exception as exc:
                        await _log(db, job.id, LogLevel.error, f"Failed to delete {rel}: {_exc_detail(exc)}", rel)
                        has_error = True

        # --- Two-way: sync destination → source ---
        if two_way:
            # Source dirs that could not be created — their contents are skipped
            src_failed_dirs: list[str] = []
            for rel in sorted(dst_map):
                dst_entry = dst_map[rel]
                if rel in src_map or rel in dst_deleted or _under_any(rel, dst_deleted_dirs):
                    continue
                if _under_any(rel, src_failed_dirs) or _under_any(rel, conflict_dirs) or exclusion.is_ignored(rel, dst_entry):
                    continue
                src_path = rule.source_path.rstrip("/") + "/" + rel.lstrip("/")
                dst_path = rule.dest_path.rstrip("/") + "/" + rel.lstrip("/")
                if dst_entry.is_dir:
                    try:
                        await src.mkcol(src_path)
                        await _log(db, job.id, LogLevel.info, f"Created dir on source: {src_path}", src_path)
                    except Exception as exc:
                        await _log(db, job.id, LogLevel.error, f"Failed to create dir {src_path} on source: {_exc_detail(exc)}", src_path)
                        src_failed_dirs.append(rel)
                        has_error = True
                    continue
                try:
                    await dst.copy_to(dst_path, src, src_path, dst_entry.size)
                    job.files_added += 1
                    job.bytes_transferred += dst_entry.size
                    await _log(db, job.id, LogLevel.info, f"Added (from dest): {rel}", rel)
                except Exception as exc:
                    await _log(db, job.id, LogLevel.error, f"Failed reverse copy {rel}: {_exc_detail(exc)}", rel)
                    has_error = True

            # Remember what is on both sides now, for the next run
            if not await _write_state(db, job.id, rule, src, dst, src_state_doc, dst_state_doc, known, conflicts):
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

    def is_ignored(self, rel: str, entry: DavEntry) -> bool:
        """Return True if the entry is excluded from syncing by any filter."""
        return (
            self.is_subfolder_excluded(rel)
            or self.is_folder_name_excluded(rel, entry.is_dir)
            or self.is_hidden_path(rel)
            or (not entry.is_dir and self.check(entry)[0])
        )

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


def _under_any(rel: str, dirs: list[str]) -> bool:
    """Return True if rel lies below one of dirs."""
    return any(rel.startswith(d + "/") for d in dirs)


def _sig(entry: DavEntry) -> list:
    """Change signature of an entry as stored in the state file: [mtime, size]."""
    return [entry.mtime.timestamp() if entry.mtime else None, entry.size]


def _two_way_action(src: DavEntry, dst: DavEntry, known: dict | None) -> str:
    """Decide how to sync a file present on both sides in two-way mode.

    Returns "none", "to_dst", "to_src" or "conflict". With a record from the last
    run, each side is compared against its own recorded [mtime, size] — mtimes of
    the two servers are never compared with each other. Without one (first run),
    same-size files are taken as in sync and otherwise the newer one wins.
    """
    if known is not None and known.get("dir") is False:
        src_changed = _sig(src) != known.get("src")
        dst_changed = _sig(dst) != known.get("dst")
        if src_changed and dst_changed:
            return "conflict"
        return "to_dst" if src_changed else "to_src" if dst_changed else "none"
    if src.size == dst.size:
        return "none"
    if src.mtime and dst.mtime:
        return "to_dst" if src.mtime >= dst.mtime else "to_src"
    return "conflict"


async def _same_content(
    src: WebDAVClient, src_path: str, dst: WebDAVClient, dst_path: str, src_entry: DavEntry, dst_entry: DavEntry,
) -> bool:
    """Return True if both files have identical content (only checked up to SAME_CONTENT_MAX_BYTES)."""
    if src_entry.size != dst_entry.size or src_entry.size > SAME_CONTENT_MAX_BYTES:
        return False
    try:
        return await src.get_bytes(src_path) == await dst.get_bytes(dst_path)
    except Exception:
        return False


async def _read_state(db: AsyncSession, job_id: int, client: WebDAVClient, root: str, side: str) -> dict:
    """Load the state document from a sync root; empty if missing or unreadable."""
    path = root.rstrip("/") + STATE_REL
    try:
        doc = json.loads(await client.get_bytes(path))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            await _log(db, job_id, LogLevel.warning, f"Could not read sync state on {side}: {_exc_detail(exc)}", path)
        return {}
    except Exception as exc:
        await _log(db, job_id, LogLevel.warning, f"Ignoring unreadable sync state on {side}: {exc}", path)
        return {}
    if not isinstance(doc, dict) or doc.get("version") != STATE_VERSION or not isinstance(doc.get("rules"), dict):
        await _log(db, job_id, LogLevel.warning, f"Ignoring sync state on {side} with unknown format", path)
        return {}
    return doc


def _rule_state(doc: dict, rule: SyncRule) -> dict | None:
    """Return the entries recorded for this rule, or None if absent or recorded for other paths."""
    state = doc.get("rules", {}).get(str(rule.id))
    if (
        not isinstance(state, dict)
        or state.get("source_path") != rule.source_path.rstrip("/")
        or state.get("dest_path") != rule.dest_path.rstrip("/")
        or not isinstance(state.get("entries"), dict)
    ):
        return None
    return state["entries"]


def _known_entries(rule: SyncRule, src_doc: dict, dst_doc: dict) -> dict[str, dict]:
    """Entries that were on both sides after the last run, per the state on both sides.

    Only entries recorded in both state files count — if one write failed or a file
    is missing, the sync falls back to not deleting anything it isn't sure about.
    """
    src_entries = _rule_state(src_doc, rule)
    dst_entries = _rule_state(dst_doc, rule)
    if src_entries is None or dst_entries is None:
        return {}
    return {rel: e for rel, e in src_entries.items() if rel in dst_entries}


def _dirty_paths(side_map: dict[str, DavEntry], known: dict[str, dict], side: str) -> set[str]:
    """Paths on one side that are new or changed since the last run, plus all their ancestors.

    A dirty entry must not be deleted, even if it was deleted on the other side —
    for a dir that means it still holds something worth keeping.
    """
    dirty: set[str] = set()
    for rel, entry in side_map.items():
        k = known.get(rel)
        if k is not None and k.get("dir") == entry.is_dir and (entry.is_dir or k.get(side) == _sig(entry)):
            continue
        parts = rel.split("/")
        for i in range(2, len(parts) + 1):
            dirty.add("/".join(parts[:i]))
    return dirty


async def _write_state(
    db: AsyncSession,
    job_id: int,
    rule: SyncRule,
    src: WebDAVClient,
    dst: WebDAVClient,
    src_doc: dict,
    dst_doc: dict,
    known: dict[str, dict],
    conflicts: set[str],
) -> bool:
    """Record the entries now present on both sides in the state file of both roots.

    Conflicting entries keep their previous record (or stay unrecorded), so the
    conflict is reported again on every run until it is resolved.
    """
    try:
        src_map = _build_map(await src.propfind(rule.source_path, depth="infinity"), rule.source_path)  # type: ignore[arg-type]
        dst_map = _build_map(await dst.propfind(rule.dest_path, depth="infinity"), rule.dest_path)  # type: ignore[arg-type]
    except Exception as exc:
        await _log(db, job_id, LogLevel.error, f"Failed to list trees for sync state: {_exc_detail(exc)}")
        return False

    exclusion = _Exclusion(rule)
    entries = {
        rel: {"dir": s.is_dir, "src": _sig(s), "dst": _sig(dst_map[rel])}
        for rel, s in src_map.items()
        if rel != STATE_REL
        and rel in dst_map
        and dst_map[rel].is_dir == s.is_dir
        and not exclusion.is_ignored(rel, s)
        and rel not in conflicts
    }
    entries.update({rel: known[rel] for rel in conflicts if rel in known})
    rule_state = {
        "source_path": rule.source_path.rstrip("/"),
        "dest_path": rule.dest_path.rstrip("/"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }

    ok = True
    for side, client, root, doc in (
        ("source", src, rule.source_path, src_doc),
        ("destination", dst, rule.dest_path, dst_doc),
    ):
        # Keep the state of other rules sharing this root
        rules = dict(doc.get("rules", {}))
        rules[str(rule.id)] = rule_state
        path = root.rstrip("/") + STATE_REL
        data = json.dumps({"version": STATE_VERSION, "rules": rules}, separators=(",", ":")).encode()
        try:
            await client.put_bytes(path, data, "application/json")
        except Exception as exc:
            await _log(db, job_id, LogLevel.error, f"Failed to write sync state on {side}: {_exc_detail(exc)}", path)
            ok = False
    return ok


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
