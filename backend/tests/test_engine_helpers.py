"""Pure helper functions of the sync engine."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from backend.sync.engine import (
    STATE_VERSION,
    _body_excerpt,
    _build_map,
    _dirty_paths,
    _exc_detail,
    _Exclusion,
    _failed_ancestor,
    _fmt_bytes,
    _is_changed,
    _known_entries,
    _sig,
    _two_way_action,
    _under_any,
)
from backend.sync.webdav import DavEntry

T = datetime(2026, 1, 1, tzinfo=timezone.utc)


def entry(rel: str, size: int = 1, mtime: datetime | None = T, is_dir: bool = False) -> DavEntry:
    return DavEntry(
        href="/dav" + rel, rel_path=rel + ("/" if is_dir else ""), name=rel.rsplit("/", 1)[-1],
        is_dir=is_dir, etag=None, mtime=mtime, size=0 if is_dir else size,
    )


def rule(**kw):
    values = dict(
        id=1, source_path="/src", dest_path="/dst", exclude_patterns=None, min_file_size=None,
        max_file_size=None, exclude_hidden=True, exclude_subfolders=None, exclude_folder_names=None,
    )
    values.update(kw)
    return SimpleNamespace(**values)


# ----------------------------------------------------------------------
# Tree comparison
# ----------------------------------------------------------------------

def test_build_map_strips_root_and_trailing_slashes():
    entries = [entry("/src", is_dir=True), entry("/src/a", is_dir=True), entry("/src/a/f.txt")]
    assert set(_build_map(entries, "/src/")) == {"/a", "/a/f.txt"}


@pytest.mark.parametrize(
    "src, dst, changed",
    [
        (entry("/f", size=1), entry("/f", size=2), True),
        (entry("/f", mtime=T + timedelta(1)), entry("/f", mtime=T), True),
        (entry("/f", mtime=T), entry("/f", mtime=T + timedelta(1)), False),
        (entry("/f", mtime=None), entry("/f"), False),
    ],
)
def test_is_changed(src, dst, changed):
    assert _is_changed(src, dst) is changed


def test_under_any_and_failed_ancestor():
    assert _under_any("/a/b", ["/a"])
    assert not _under_any("/a", ["/a"])
    assert not _under_any("/ab/c", ["/a"])
    assert _failed_ancestor("/x/y/z", {"/x": 0}) == "/x"
    assert _failed_ancestor("/xy", {"/x": 0}) is None


def test_fmt_bytes():
    assert _fmt_bytes(512) == "512.0 B"
    assert _fmt_bytes(1536) == "1.5 KB"
    assert _fmt_bytes(5 * 1024**4) == "5.0 TB"


# ----------------------------------------------------------------------
# Exclusions
# ----------------------------------------------------------------------

def test_exclusion_patterns_and_sizes():
    ex = _Exclusion(rule(exclude_patterns=json.dumps([r"\.log$"]), min_file_size=2, max_file_size=10))
    assert ex.check(entry("/a.log", size=5))[0]
    assert "pattern" in ex.check(entry("/a.log", size=5))[1]
    assert "below min" in ex.check(entry("/a.txt", size=1))[1]
    assert "exceeds max" in ex.check(entry("/a.txt", size=11))[1]
    assert ex.check(entry("/a.txt", size=5)) == (False, "")


def test_exclusion_subfolders_are_relative_to_source_path():
    ex = _Exclusion(rule(exclude_subfolders=json.dumps(["/src/skip/", "other"])))
    assert ex.is_subfolder_excluded("/skip")
    assert ex.is_subfolder_excluded("/skip/deep/f")
    assert ex.is_subfolder_excluded("/other/f")
    assert not ex.is_subfolder_excluded("/skipper")
    assert ex.is_excluded_subfolder_root("/skip")
    assert not ex.is_excluded_subfolder_root("/skip/deep")


def test_exclusion_folder_names_at_any_depth():
    ex = _Exclusion(rule(exclude_folder_names=json.dumps(["node_modules", " "])))
    assert ex.is_folder_name_excluded("/a/node_modules", is_dir=True)
    assert ex.is_folder_name_excluded("/a/node_modules/x/y.js", is_dir=False)
    # A *file* named like the folder is not excluded
    assert not ex.is_folder_name_excluded("/a/node_modules", is_dir=False)
    assert ex.is_excluded_folder_name_root("/a/node_modules", is_dir=True)
    assert not ex.is_excluded_folder_name_root("/a/node_modules/b/node_modules", is_dir=True)


@pytest.mark.parametrize("rel", ["/.git", "/a/.hidden/x", "/doc~", "/x.BAK", "/y.tmp"])
def test_exclusion_hidden_paths(rel):
    assert _Exclusion(rule()).is_hidden_path(rel)
    assert not _Exclusion(rule(exclude_hidden=False)).is_hidden_path(rel)


def test_is_ignored_combines_all_filters():
    ex = _Exclusion(rule(exclude_subfolders='["/src/s"]', exclude_folder_names='["nm"]', max_file_size=5))
    assert ex.is_ignored("/s/f", entry("/s/f"))
    assert ex.is_ignored("/nm/f", entry("/nm/f"))
    assert ex.is_ignored("/.h", entry("/.h"))
    assert ex.is_ignored("/big", entry("/big", size=6))
    assert not ex.is_ignored("/big", entry("/big", size=6, is_dir=True))
    assert not ex.is_ignored("/ok", entry("/ok"))


# ----------------------------------------------------------------------
# Two-way state
# ----------------------------------------------------------------------

def record(src: DavEntry, dst: DavEntry) -> dict:
    return {"dir": src.is_dir, "src": _sig(src), "dst": _sig(dst)}


@pytest.mark.parametrize(
    "src_changed, dst_changed, expected",
    [(False, False, "none"), (True, False, "to_dst"), (False, True, "to_src"), (True, True, "conflict")],
)
def test_two_way_action_with_state(src_changed, dst_changed, expected):
    s, d = entry("/f", mtime=T), entry("/f", mtime=T + timedelta(hours=1))
    known = record(s, d)
    s2 = entry("/f", mtime=T + timedelta(days=1)) if src_changed else s
    d2 = entry("/f", size=7) if dst_changed else d
    assert _two_way_action(s2, d2, known) == expected


def test_two_way_action_without_state():
    assert _two_way_action(entry("/f", size=3), entry("/f", size=3, mtime=T + timedelta(1)), None) == "none"
    assert _two_way_action(entry("/f", size=3, mtime=T + timedelta(1)), entry("/f", size=4), None) == "to_dst"
    assert _two_way_action(entry("/f", size=3), entry("/f", size=4, mtime=T + timedelta(1)), None) == "to_src"
    assert _two_way_action(entry("/f", size=3, mtime=None), entry("/f", size=4), None) == "conflict"


def test_two_way_action_ignores_a_dir_record():
    # Recorded as a dir last time, a file now: fall back to the no-state rules
    assert _two_way_action(entry("/f", size=3), entry("/f", size=3), {"dir": True}) == "none"


def test_dirty_paths_marks_new_and_changed_entries_and_their_ancestors():
    side = {
        "/a": entry("/a", is_dir=True),
        "/a/same": entry("/a/same"),
        "/b": entry("/b", is_dir=True),
        "/b/c": entry("/b/c", is_dir=True),
        "/b/c/changed": entry("/b/c/changed", size=9),
        "/new": entry("/new"),
    }
    known = {
        "/a": {"dir": True}, "/a/same": record(entry("/a/same"), entry("/a/same")),
        "/b": {"dir": True}, "/b/c": {"dir": True},
        "/b/c/changed": record(entry("/b/c/changed"), entry("/b/c/changed")),
    }
    assert _dirty_paths(side, known, "src") == {"/b", "/b/c", "/b/c/changed", "/new"}


def test_dirty_paths_type_change_is_dirty():
    assert _dirty_paths({"/x": entry("/x")}, {"/x": {"dir": True}}, "src") == {"/x"}


def state_doc(rule_obj, entries: dict, **overrides) -> dict:
    state = {"source_path": rule_obj.source_path, "dest_path": rule_obj.dest_path, "entries": entries}
    state.update(overrides)
    return {"version": STATE_VERSION, "rules": {str(rule_obj.id): state}}


def test_known_entries_requires_both_sides():
    r = rule()
    doc = state_doc(r, {"/a": {"dir": True}, "/b": {"dir": True}})
    other = state_doc(r, {"/a": {"dir": True}})
    assert set(_known_entries(r, doc, other)) == {"/a"}
    assert _known_entries(r, doc, {}) == {}
    assert _known_entries(r, {}, doc) == {}


def test_known_entries_ignores_state_recorded_for_other_paths_or_rules():
    r = rule()
    assert _known_entries(r, state_doc(r, {"/a": {}}, source_path="/elsewhere"), state_doc(r, {"/a": {}})) == {}
    assert _known_entries(rule(id=2), state_doc(r, {"/a": {}}), state_doc(r, {"/a": {}})) == {}


# ----------------------------------------------------------------------
# Error formatting
# ----------------------------------------------------------------------

def http_error(status: int, body: str, content_type: str = "text/plain", history=()) -> httpx.HTTPStatusError:
    request = httpx.Request("PUT", "http://h.test/dav/f")
    response = httpx.Response(status, text=body, headers={"content-type": content_type}, request=request)
    response.history = list(history)
    return httpx.HTTPStatusError("err", request=request, response=response)


def test_exc_detail_sabre_error():
    body = (
        '<?xml version="1.0"?><d:error xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns">'
        "<s:exception>Sabre\\DAV\\Exception\\Forbidden</s:exception><s:message>Nope</s:message></d:error>"
    )
    detail = _exc_detail(http_error(403, body, "application/xml"))
    assert detail.startswith("HTTP 403 Forbidden for PUT http://h.test/dav/f")
    assert "Sabre\\DAV\\Exception\\Forbidden: Nope" in detail
    assert "content-type=application/xml" in detail


def test_exc_detail_html_page_and_redirects():
    first = httpx.Response(302, request=httpx.Request("PUT", "http://h.test/old"))
    body = "<html><head><title>Login</title><style>x{}</style></head><body><p>Please   sign in</p></body></html>"
    detail = _exc_detail(http_error(401, body, "text/html", history=[first]))
    assert "(redirected: 302 PUT http://h.test/old)" in detail
    assert "HTML page 'Login': Login Please sign in" in detail


def test_body_excerpt_truncates_long_bodies():
    response = httpx.Response(500, text="x" * 1000, request=httpx.Request("GET", "http://h.test"))
    assert _body_excerpt(response, limit=10) == "x" * 10 + "…"


def test_exc_detail_other_errors():
    request = httpx.Request("GET", "http://h.test")
    assert _exc_detail(httpx.ReadTimeout("t", request=request)) == "Timeout (ReadTimeout)"
    assert _exc_detail(httpx.ConnectError("refused", request=request)) == "Connection error: refused"
    assert _exc_detail(ValueError("boom")) == "boom"
