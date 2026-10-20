"""WebDAVClient against the in-memory server: requests, XML parsing, chunked uploads."""

import httpx
import pytest

from backend.sync import webdav
from backend.sync.webdav import WebDAVClient, _encode_path, _parse_propfind


def client(server) -> WebDAVClient:
    return WebDAVClient(server.base_url, "user", "pw")


async def test_propfind_depth_1_lists_direct_children(dav):
    s = dav("s")
    s.write("/a/file.txt", "hello")
    s.write("/a/sub/deep.txt", "x")

    async with client(s) as c:
        entries = {e.rel_path: e for e in await c.propfind("/a", depth=1)}

    assert set(entries) == {"/a/", "/a/file.txt", "/a/sub/"}
    f = entries["/a/file.txt"]
    assert (f.name, f.is_dir, f.size) == ("file.txt", False, 5)
    assert f.mtime is not None and f.mtime.tzinfo is not None
    assert f.etag and not f.etag.startswith('"')
    assert entries["/a/sub/"].is_dir and entries["/a/sub/"].name == "sub"


async def test_propfind_depth_infinity_lists_whole_tree(dav):
    s = dav("s")
    s.write("/a/sub/deep.txt", "x")
    async with client(s) as c:
        paths = {e.rel_path for e in await c.propfind("/a", depth="infinity")}
    assert paths == {"/a/", "/a/sub/", "/a/sub/deep.txt"}


async def test_propfind_handles_special_characters(dav):
    s = dav("s")
    s.write("/Fotos 2024/Grüße & mehr #1.txt", "x")
    async with client(s) as c:
        entries = await c.propfind("/Fotos 2024", depth=1)
    assert "/Fotos 2024/Grüße & mehr #1.txt" in {e.rel_path for e in entries}
    # The request path was percent-encoded
    assert s.requests[-1].path == "/Fotos 2024"


async def test_propfind_strips_nextcloud_base_path(dav):
    s = dav("nc", nextcloud=True)
    s.write("/Docs/a.txt", "x")
    async with client(s) as c:
        entries = await c.propfind("/Docs", depth=1)
    assert {e.rel_path for e in entries} == {"/Docs/", "/Docs/a.txt"}
    assert entries[1].href.startswith("/remote.php/dav/files/user/")


async def test_propfind_missing_path_raises(dav):
    s = dav("s")
    async with client(s) as c:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await c.propfind("/missing")
    assert exc.value.response.status_code == 404


def test_parse_propfind_skips_responses_without_200_propstat():
    xml = """<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">
      <d:response><d:href>/dav/gone</d:href>
        <d:propstat><d:prop><d:getetag/></d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>
      </d:response>
      <d:response><d:href>/dav/ok.txt</d:href>
        <d:propstat><d:prop><d:getcontentlength>bad</d:getcontentlength><d:getlastmodified>not a date</d:getlastmodified></d:prop>
        <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
      </d:response>
      <d:response></d:response>
    </d:multistatus>"""
    entries = _parse_propfind(xml, "/dav")
    assert [(e.rel_path, e.size, e.mtime, e.is_dir) for e in entries] == [("/ok.txt", 0, None, False)]


def test_encode_path_keeps_slashes_and_encodes_the_rest():
    assert _encode_path("/a b/ü#?.txt") == "/a%20b/%C3%BC%23%3F.txt"


async def test_copy_to_streams_between_servers(dav):
    src, dst = dav("src"), dav("dst")
    src.write("/f.bin", b"\x00\x01" * 1000)
    dst.mkdir("/target")
    async with client(src) as a, client(dst) as b:
        await a.copy_to("/f.bin", b, "/target/f.bin", 2000)
    assert dst.read("/target/f.bin") == b"\x00\x01" * 1000


async def test_copy_to_raises_on_missing_source(dav):
    src, dst = dav("src"), dav("dst")
    async with client(src) as a, client(dst) as b:
        with pytest.raises(httpx.HTTPStatusError):
            await a.copy_to("/missing", b, "/x", 1)


async def test_copy_to_raises_when_target_dir_is_missing(dav):
    src, dst = dav("src"), dav("dst")
    src.write("/f", "x")
    async with client(src) as a, client(dst) as b:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await a.copy_to("/f", b, "/no/such/dir/f", 1)
    assert exc.value.response.status_code == 409


async def test_chunked_upload_for_large_files_on_nextcloud(dav, monkeypatch):
    monkeypatch.setattr(webdav, "CHUNKED_UPLOAD_THRESHOLD", 10)
    monkeypatch.setattr(webdav, "UPLOAD_CHUNK_SIZE", 4)
    src, dst = dav("src"), dav("nc", nextcloud=True)
    data = b"0123456789abcdefghij-"  # 21 bytes → chunks of 4,4,4,4,4,1
    src.write("/big", data)

    async with client(src) as a, client(dst) as b:
        await a.copy_to("/big", b, "/big", len(data), chunk_size=3)

    assert dst.read("/big") == data
    chunk_puts = [r for r in dst.requests if r.method == "PUT"]
    assert len(chunk_puts) == 6
    assert dst.count("MOVE") == 1
    # The temporary upload dir was assembled and removed
    assert not any("/uploads/user/next-sync-" in p for p in dst.nodes)


async def test_chunked_upload_cleans_up_on_failure(dav, monkeypatch):
    monkeypatch.setattr(webdav, "CHUNKED_UPLOAD_THRESHOLD", 1)
    src, dst = dav("src"), dav("nc", nextcloud=True)
    src.write("/big", "data")
    # Every MOVE (the final assembly) fails
    real_handle = dst.handle

    async def failing_move(request):
        if request.method == "MOVE":
            return httpx.Response(507)
        return await real_handle(request)

    dst.handle = failing_move
    async with client(src) as a, client(dst) as b:
        with pytest.raises(httpx.HTTPStatusError):
            await a.copy_to("/big", b, "/big", 4)
    assert not dst.exists("/big")
    assert not any("/uploads/user/next-sync-" in p for p in dst.nodes)


async def test_small_files_on_nextcloud_use_a_plain_put(dav):
    src, dst = dav("src"), dav("nc", nextcloud=True)
    src.write("/small", "x")
    async with client(src) as a, client(dst) as b:
        await a.copy_to("/small", b, "/small", 1)
    assert dst.read("/small") == b"x"
    assert dst.count("MOVE") == 0


async def test_get_and_put_bytes(dav):
    s = dav("s")
    async with client(s) as c:
        await c.put_bytes("/state.json", b"{}", "application/json")
        assert await c.get_bytes("/state.json") == b"{}"


async def test_mkcol_ignores_existing_dir_and_raises_on_missing_parent(dav):
    s = dav("s")
    s.mkdir("/exists")
    async with client(s) as c:
        await c.mkcol("/exists")
        await c.mkcol("/new")
        with pytest.raises(httpx.HTTPStatusError):
            await c.mkcol("/no/parent")
    assert s.is_dir("/new")


async def test_delete_removes_recursively_and_raises_when_missing(dav):
    s = dav("s")
    s.write("/d/a/b.txt", "x")
    async with client(s) as c:
        await c.delete("/d")
        with pytest.raises(httpx.HTTPStatusError):
            await c.delete("/d")
    assert not s.exists("/d/a/b.txt")


async def test_get_quota(dav):
    s = dav("s")
    s.quota = (123, 456)
    async with client(s) as c:
        assert await c.get_quota() == (123, 456)
    s.quota = (123, -3)  # negative = unlimited/unknown
    async with client(s) as c:
        assert await c.get_quota() == (123, None)


async def test_test_connection(dav):
    s = dav("s")
    async with client(s) as c:
        assert await c.test_connection() is True
    async with WebDAVClient("http://unknown.test/dav", "u", "p") as c:
        assert await c.test_connection() is False
